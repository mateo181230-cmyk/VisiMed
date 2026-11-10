"""Idempotent, isolated demonstration records; never overwrites real panel facts."""
import copy
import uuid
from datetime import datetime, time, timedelta

from sqlalchemy import select, func
from uno import clock
from uno.db import next_change_seq
from uno.modules.auth.models import User
from uno.modules.catalog.models import Doctor, Institution, Panel, Product
from uno.modules.agenda.models import Visit, VisitLine
from uno.modules.calls.models import VisitReport, Call
from uno.modules.calls.snc_report import SNCReport, legacy_projection
from uno.modules.journey.models import VisitPreparation
from uno.modules.workflows.models import VisitLearning, FollowupTask
from uno.modules.workflows.tasks import reconcile_tasks
from uno.modules.marketing.models import MarketingActivity
from .models import (PanelContact, ReceptionAvailability, LocationVerification,
                     MedicalPotential, Pharmacy, PharmacyVisit, VisitRequirement, RoutePolicy)
from .schemas import PotentialInput, PharmacyReport
from .service import ZONE

NOTE = 'ESCENARIO DE DEMOSTRACIÓN. Cifras y resultados ilustrativos; no representan actividad real del médico ni del piloto.'


async def populate(session, rep_id, source_reps, line_id, anchor):
    """Caller owns the transaction and backup. Real IDs never receive demo facts."""
    now = clock.now()
    rep = await session.get(User, rep_id)
    assert rep and rep.role == 'rep' and rep_id not in source_reps
    sources = (await session.scalars(select(PanelContact).where(
        PanelContact.representative_id.in_(source_reps)).order_by(PanelContact.source_key))).all()
    assert sources, 'No source panel'
    before = [(r.id, r.representative_id, copy.deepcopy(r.data), r.active) for r in sources]
    call_count = await session.scalar(select(func.count()).select_from(Call))
    namespace = uuid.uuid5(rep_id, 'novamed-demo-20261016')
    uid = lambda kind, val: uuid.uuid5(namespace, f'{kind}:{val}')
    rep.pilot_scope = {**(rep.pilot_scope or {}), 'line_ids':[str(line_id)],
                      'demo_mode': True, 'demo_dataset': 'novamed-demo-20261016'}
    sites, doctors, cloned = {}, {}, []

    async def clone_site(id):
        if id in sites:
            return sites[id]
        original = await session.get(Institution, id)
        target_id = uid('site', id)
        row = await session.get(Institution, target_id)
        if not row:
            row = Institution(id=target_id, name=('Demo · '+original.name)[:160],
                address=original.address, city=original.city, lat=original.lat, lng=original.lng,
                radius_m=original.radius_m, ref_source='demo_copy', created_by=rep_id,
                created_at=now, change_seq=await next_change_seq(session))
            session.add(row)
            await session.flush()
            geo = await session.get(LocationVerification, id)
            if geo:
                session.add(LocationVerification(institution_id=target_id, version=1,
                    status=geo.status, source=geo.source, evidence={**copy.deepcopy(geo.evidence),
                    'demo': True, 'source_institution_id': str(id)}, updated_by=rep_id, updated_at=now))
        sites[id] = row
        return row

    for source in sources:
        site = await clone_site(source.institution_id)
        doctor_id = uid('doctor', source.doctor_id)
        if source.doctor_id not in doctors:
            original = await session.get(Doctor, source.doctor_id)
            doctor = await session.get(Doctor, doctor_id)
            if not doctor:
                doctor = Doctor(id=doctor_id, full_name=('Demo · '+original.full_name)[:160],
                    specialty=original.specialty, institution_id=site.id, review_state='approved',
                    created_by=rep_id, created_at=now, change_seq=await next_change_seq(session))
                session.add(doctor)
                await session.flush()
            doctors[source.doctor_id] = doctor
            if not await session.get(Panel, (rep_id, doctor_id)):
                session.add(Panel(representative_id=rep_id, doctor_id=doctor_id,
                    default_line_id=line_id, change_seq=await next_change_seq(session)))
        contact_id = uid('contact', source.id)
        if not await session.get(PanelContact, contact_id):
            session.add(PanelContact(id=contact_id, representative_id=rep_id, doctor_id=doctor_id,
                institution_id=site.id, source_key='demo:'+str(source.id), active=source.active,
                data={**copy.deepcopy(source.data), 'demo':True, 'source_contact_id':str(source.id),
                'source_representative_id':str(source.representative_id)}, updated_at=now))
        availability = await session.get(ReceptionAvailability, (source.doctor_id, source.institution_id))
        if availability and not await session.get(ReceptionAvailability, (doctor_id, site.id)):
            session.add(ReceptionAvailability(doctor_id=doctor_id, institution_id=site.id,
                version=1, data=copy.deepcopy(availability.data), updated_by=rep_id, updated_at=now))
        cloned.append((doctors[source.doctor_id], site, source))
    await session.flush()

    # A questionnaire is a separate example record, never a claimed observation.
    active = [row for row in cloned if row[2].active]
    assert active, 'No active source contacts'
    for n, (doctor, site, _) in enumerate(active[:36]):
        if await session.get(MedicalPotential, (doctor.id, site.id)):
            continue
        patients = 14 + (n % 7) * 3
        eps, private, prepaid = patients//2, patients//5, patients//6
        data = PotentialInput(doctor_id=doctor.id, institution_id=site.id,
            practice_days=list(range(3+n%3)), patients_per_day=patients,
            consultations={'eps':eps,'private':private,'prepaid':prepaid,
                           'complementary':patients-eps-private-prepaid,'unknown':0},
            snc_percentage=40+(n%5)*10, source='document', observed_on=anchor, notes=NOTE)
        session.add(MedicalPotential(doctor_id=doctor.id, institution_id=site.id,
            data=data.model_dump(mode='json'), version=1, updated_by=rep_id, updated_at=now))

    # Preserve each original frequency, cycle and reception window verbatim.
    requirements=(await session.scalars(select(VisitRequirement).where(
        VisitRequirement.representative_id.in_(source_reps), VisitRequirement.active.is_(True)))).all()
    for original in requirements:
        if original.doctor_id not in doctors or original.institution_id not in sites:
            continue
        id=uid('requirement', original.id)
        if not await session.get(VisitRequirement, id):
            session.add(VisitRequirement(id=id, representative_id=rep_id,
                doctor_id=doctors[original.doctor_id].id, institution_id=sites[original.institution_id].id,
                cycle_start=original.cycle_start, cycle_end=original.cycle_end,
                data=copy.deepcopy(original.data), version=1, active=True, updated_at=now))
    policy=await session.get(RoutePolicy, rep_id)
    if not policy:
        template=await session.get(RoutePolicy, source_reps[0])
        if template:
            data={**copy.deepcopy(template.data),'representative_id':str(rep_id)}
            assert data.get('allow_unconfirmed_reception') is False
            session.add(RoutePolicy(representative_id=rep_id, data=data, active=template.active,
                approved_by=template.approved_by, version=1, updated_at=now))

    products=(await session.scalars(select(Product).where(Product.line_id==line_id,
        Product.active.is_(True)).order_by(Product.name))).all()
    assert len(products)>=2
    # Representative examples use the real product catalog and actual report schema.
    days=[]
    d=anchor-timedelta(days=1)
    while len(days)<15:
        if d.weekday()<5:days.append(d)
        d-=timedelta(days=1)
    for n in range(75):
        doctor, site, _=active[n%min(30,len(active))]
        dt=datetime.combine(days[n//5],time(8+(n%5)*2,15),ZONE)
        id=uid('history',n)
        if await session.get(Visit,id):continue
        visit=Visit(id=id,representative_id=rep_id,doctor_id=doctor.id,institution_id=site.id,
            primary_line_id=line_id,scheduled_at=dt,title='Demostración · Visita SNC',
            status='confirmed',planned_by='demo',arrived_at=dt,finished_at=dt+timedelta(minutes=5),
            report_mode='manual',created_at=dt,updated_at=dt,change_seq=await next_change_seq(session))
        session.add(visit);await session.flush()
        session.add(VisitLine(visit_id=id,line_id=line_id))
        selected=[products[n%len(products)],products[(n+1)%len(products)]]
        result=['achieved','partial','not_achieved'][n%3]
        data=SNCReport(products=[{'position':i+1,'name':p.name,
            'objective':'Demo: identificar una pregunta sobre el material aprobado.',
            'metric':'Preguntas identificadas','target':1,'unit':'pregunta','due_date':dt.date(),
            'achievement':result,'evidence':NOTE+' Se solicitó revisar la evidencia del material aprobado.',
            'barriers':([] if n%3==0 else ['Demo: tiempo limitado para revisar la evidencia'])}
            for i,p in enumerate(selected)], referrals=[],referrals_evidence='Demo: no se realizó direccionamiento.',
            commitments=[{'owner':'representative','action':'Demo: preparar la respuesta con el material SNC aprobado.',
                'due_date':anchor+timedelta(days=(n%7)-3),'next_objective':'Demo: resolver la pregunta pendiente y verificar comprensión.'}],
            commitments_evidence='Demo: compromiso ilustrativo.',sequence_evidence='Demo: orden ilustrativo del catálogo SNC.')
        fields={k:{'value':v,'confidence':'high','source':'rep_edit'} for k,v in legacy_projection(data).items()}
        fields['snc_report_json']={'value':data.model_dump_json(),'confidence':'high','source':'rep_edit'}
        report=VisitReport(visit_id=id,status='confirmed',fields=fields,complete=not data.missing(),
            problems=data.missing(),extractor_version='demo-illustrative-v1',created_at=dt,
            updated_at=dt+timedelta(minutes=7),confirmed_at=dt+timedelta(minutes=7),change_seq=await next_change_seq(session))
        session.add(report)
        session.add(VisitLearning(visit_id=id,data={'objectives':[{'product_id':str(p.id),
            'objective':'Demo: identificar una pregunta sobre el material aprobado.',
            'measure':'1 pregunta identificada','due':str(dt.date())} for p in selected]},version=1,updated_at=dt))
        session.add(VisitPreparation(visit_id=id,objective='Demo: preparar la evidencia SNC aprobada.',
            active_seconds=90+n,prepared_at=dt-timedelta(minutes=10),created_at=dt-timedelta(minutes=15),updated_at=dt))
        await reconcile_tasks(session,visit,report,now)
    await session.flush()
    demo_tasks=(await session.scalars(select(FollowupTask).where(FollowupTask.representative_id==rep_id,
        FollowupTask.action.like('Demo:%')).order_by(FollowupTask.source_key))).all()
    for n,t in enumerate(demo_tasks):
        if n%3==0 and t.version==1:
            t.status='done';t.evidence=NOTE+' Material revisado en el ensayo.';t.version=2

    # The only synthetic future appointments are explicitly internal office exercises.
    office=await session.scalar(select(Institution).where(Institution.ref_source=='demo',Institution.created_by==rep_id))
    office_doctor=await session.scalar(select(Doctor).where(Doctor.institution_id==office.id)) if office else None
    if office_doctor:
        for offset in (0,3,4,5,6,7):
            day=anchor+timedelta(days=offset)
            if day.weekday()>4:continue
            id=uuid.uuid5(office_doctor.id,str(rep_id)+str(day))
            v=await session.get(Visit,id)
            if not v:
                v=Visit(id=id,representative_id=rep_id,doctor_id=office_doctor.id,institution_id=office.id,
                    primary_line_id=line_id,scheduled_at=datetime.combine(day,time(9),ZONE),
                    title='Demo interna en Novamed · Prueba de la app',planned_by='demo',status='scheduled',
                    created_at=now,updated_at=now,change_seq=await next_change_seq(session))
                session.add(v);await session.flush();session.add(VisitLine(visit_id=id,line_id=line_id))
            if not await session.get(VisitLearning,id):
                session.add(VisitLearning(visit_id=id,data={'objectives':[{'product_id':str(p.id),
                    'objective':'Demo: resolver una pregunta con el material SNC aprobado.',
                    'measure':'1 pregunta resuelta','due':str(day)} for p in products[:2]]},version=1,updated_at=now))

    for n in range(6):
        id=uid('marketing',n)
        if await session.get(MarketingActivity,id):continue
        dt=datetime.combine(anchor+timedelta(days=n-3),time(15,30),ZONE)
        completed=n<3
        unique_people={str(row[0].id):row[0] for row in active}
        people=[{'doctor_id':str(d.id),'name':d.full_name,
                 'specialty':d.specialty or 'Medicina general'} for d in list(unique_people.values())[:5+n]]
        data={'demo':True,'notes':NOTE,'planned_attendees':12,'product_ids':[str(p.id) for p in products[:3]],
              'products':[{'id':str(p.id),'name':p.name} for p in products[:3]],
              'consultation_types':['eps','private'],'attendees':people,
              'materials':[{'name':'Material SNC aprobado · Demo','quantity':len(people)}],
              'outcome':NOTE+' Revisión de preguntas y material de producto.' if completed else '',
              'next_action':'Demo: revisar las preguntas en la próxima preparación.'}
        session.add(MarketingActivity(id=id,representative_id=rep_id,line_id=line_id,
            institution_id=(office.id if office else active[0][1].id),status='completed' if completed else 'scheduled',
            kind='training',objective='Demo: revisar el material SNC y resolver preguntas con el equipo.',
            starts_at=dt,ends_at=dt+timedelta(minutes=45),started_at=dt if completed else None,
            completed_at=dt+timedelta(minutes=45) if completed else None,data=data,version=1,
            created_by=rep_id,updated_by=rep_id,created_at=now,updated_at=now))

    pharmacies=(await session.scalars(select(Pharmacy).where(Pharmacy.representative_id.in_(source_reps)))).all()
    for n,original in enumerate(pharmacies):
        site=await clone_site(original.institution_id);id=uid('pharmacy',original.id)
        if not await session.get(Pharmacy,id):
            session.add(Pharmacy(id=id,institution_id=site.id,representative_id=rep_id,chain=original.chain,
                data={**copy.deepcopy(original.data),'demo':True,'source_pharmacy_id':str(original.id)},
                active=original.active,version=1,updated_at=now));await session.flush()
        if n>=6:continue
        visitid=uid('pharmacy-history',n)
        if await session.get(PharmacyVisit,visitid):continue
        dt=datetime.combine(anchor-timedelta(days=1+n),time(16,30),ZONE)
        report=PharmacyReport(id=visitid,observations=[{'product_id':products[n%len(products)].id,
            'stock':8+n,'unit':'cajas','rotation':2+n,'period_days':30,'source':'declared'}],
            action=NOTE,result='partial',barriers='Demo: verificar disponibilidad en el siguiente contacto.',
            followups=[{'action':'Demo: revisar disponibilidad.','due_on':anchor+timedelta(days=3),'owner':'representative'}],confirmed=True)
        session.add(PharmacyVisit(id=visitid,pharmacy_id=id,representative_id=rep_id,
            scheduled_at=dt,status='confirmed',planned_by='demo',arrived_at=dt,finished_at=dt+timedelta(minutes=7),
            report=report.model_dump(mode='json'),version=1,updated_at=now))
    await session.flush()
    assert before==[(r.id,r.representative_id,r.data,r.active) for r in sources]
    assert call_count==await session.scalar(select(func.count()).select_from(Call)), 'Seed must never place calls'
    return {'copied_contacts':len(cloned),'copied_doctors':len(doctors),'potential_examples':min(36,len(active)),
            'history_examples':75,'marketing_examples':6,'pharmacies':len(pharmacies),
            'real_panel_unchanged':True,'calls_created':0}
