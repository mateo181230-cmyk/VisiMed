"""Explicit office demonstration using the real agenda, report and learning records."""
import uuid
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from uno import clock
from uno.db import next_change_seq
from uno.deps import get_current_user, get_session
from uno.errors import ApiError
from uno.modules.agenda.handlers import VisitTouchPayload, visit_arrived, visit_finished
from uno.modules.agenda.models import Visit, VisitLine
from uno.modules.catalog.models import Doctor, Institution, Panel, Product
from uno.modules.journey.models import VisitPreparation
from uno.modules.workflows.models import VisitLearning
from uno.modules.sync.registry import EventContext, Rejected
from .service import ZONE

router = APIRouter(prefix="/v1/territory/demo", tags=["office-demo"])


async def definition(session, actor):
    if actor.role != "rep":
        raise ApiError(403, "representative_required", "Abre la demo con la cuenta de Juliana")
    row = (await session.execute(select(Doctor, Institution, Panel)
        .join(Institution, Doctor.institution_id == Institution.id)
        .join(Panel, Panel.doctor_id == Doctor.id)
        .where(Panel.representative_id == actor.id, Institution.ref_source == "demo"))).first()
    if not row:
        raise ApiError(404, "demo_not_assigned", "Esta cuenta no tiene una demostración asignada")
    return row


def render(doctor, site, visit):
    return {"doctor": doctor.full_name, "doctor_id": str(doctor.id), "institution": site.name,
            "address": site.address, "lat": site.lat, "lng": site.lng, "radius_m": site.radius_m,
            "visit_id": str(visit.id) if visit else None, "status": visit.status if visit else None,
            "is_demo": True, "counts_in_pilot": False,
            "arrival_distance_m": visit.arrival_distance_m if visit else None}


@router.get("")
async def current(actor=Depends(get_current_user), session=Depends(get_session)):
    doctor, site, _ = await definition(session, actor)
    end = datetime.combine(clock.now().astimezone(ZONE).date()+timedelta(days=1), time(), ZONE)
    visit = await session.scalar(select(Visit).where(Visit.representative_id == actor.id,
        Visit.doctor_id == doctor.id, Visit.planned_by == "demo", Visit.scheduled_at < end)
        .order_by(Visit.created_at.desc(), Visit.scheduled_at.desc()).limit(1))
    return render(doctor, site, visit)


async def add_preparation(session, visit):
    products = (await session.scalars(select(Product).where(Product.line_id == visit.primary_line_id,
        Product.active.is_(True), Product.name.in_(['ESLUX', 'ESCILOM'])).order_by(Product.name.desc()))).all()
    now = clock.now()
    if not await session.get(VisitLearning, visit.id):
        session.add(VisitLearning(visit_id=visit.id, data={'objectives':[
            {'product_id':str(p.id), 'objective':('Demo: resolver dos preguntas sobre el material aprobado de '+p.name+'.'),
             'measure':'2 preguntas resueltas y comprensión verificada', 'due':str(visit.scheduled_at.astimezone(ZONE).date())}
            for p in products]}, version=1, updated_at=now))
    if not await session.get(VisitPreparation, visit.id):
        session.add(VisitPreparation(visit_id=visit.id,
            objective='Demo: resolver dos preguntas de la Dra. Juliana con el material SNC aprobado; verificar comprensión y acordar el siguiente paso.',
            rep_commitment='Revisar ESLUX y ESCILOM; llevar las fuentes aprobadas y distinguir evidencia de hipótesis.',
            objective_edited=True, rep_commitment_edited=True, created_at=now, updated_at=now))


@router.post("/prepare")
async def prepare(actor=Depends(get_current_user), session=Depends(get_session)):
    doctor, site, panel = await definition(session, actor)
    now = clock.now()
    # Stable ID makes a retry safe and keeps the demo from creating duplicate visits.
    id = uuid.uuid5(doctor.id, str(actor.id) + str(now.astimezone(ZONE).date()))
    visit = await session.get(Visit, id)
    if not visit:
        visit = Visit(id=id, representative_id=actor.id, doctor_id=doctor.id,
            institution_id=site.id, primary_line_id=panel.default_line_id,
            scheduled_at=now, planned_by="demo", title="Demostración en Novamed",
            created_at=now, updated_at=now, change_seq=await next_change_seq(session))
        session.add(visit)
        await session.flush()
        session.add(VisitLine(visit_id=id, line_id=panel.default_line_id))
    await add_preparation(session, visit)
    await session.commit()
    return render(doctor, site, visit)


class Rehearsal(BaseModel):
    request_id: uuid.UUID


@router.post('/rehearsal')
async def rehearsal(body: Rehearsal, actor=Depends(get_current_user), session=Depends(get_session)):
    doctor, site, panel = await definition(session, actor)
    id = uuid.uuid5(doctor.id, str(actor.id)+':rehearsal:'+str(body.request_id))
    visit = await session.get(Visit, id)
    if not visit:
        now = clock.now()
        visit = Visit(id=id, representative_id=actor.id, doctor_id=doctor.id,
            institution_id=site.id, primary_line_id=panel.default_line_id,
            scheduled_at=now, planned_by='demo', report_mode='browser', title='Ensayo en Novamed · Datos de demostración',
            created_at=now, updated_at=now, change_seq=await next_change_seq(session))
        session.add(visit)
        await session.flush()
        session.add(VisitLine(visit_id=id, line_id=panel.default_line_id))
        await add_preparation(session, visit)
        await session.commit()
    return render(doctor, site, visit)


@router.post("/{id}/{action}")
async def touch(id: uuid.UUID, action: str, body: VisitTouchPayload,
                actor=Depends(get_current_user), session=Depends(get_session)):
    doctor, site, _ = await definition(session, actor)
    visit = await session.scalar(select(Visit).where(Visit.id == id,
        Visit.representative_id == actor.id, Visit.doctor_id == doctor.id,
        Visit.planned_by == "demo").with_for_update())
    if not visit or action not in ("arrive", "finish"):
        raise ApiError(404, "not_found", "No encontramos esta acción de demostración")
    if (action == "arrive" and visit.arrived_at) or (action == "finish" and visit.finished_at):
        return render(doctor, site, visit)
    now = clock.now()
    ctx = EventContext(session, actor, uuid.uuid4(), visit.id, None, now, now)
    try:
        await (visit_arrived(ctx, body) if action == "arrive" else visit_finished(ctx, body))
        if action == "finish":
            visit.report_mode = "browser"
    except Rejected as e:
        await session.rollback()
        message = {"demo_outside_office": "Acércate a Novamed: debes estar a 150 metros o menos del punto registrado.",
                   "demo_requires_current_gps": "Activa la ubicación precisa y vuelve a intentar. Se necesita una lectura reciente con precisión de 100 metros o mejor.",
                   "demo_requires_arrival": "Primero registra la llegada en Novamed."}.get(e.reason, "Actualiza la visita y revisa su estado.")
        raise ApiError(422, e.reason, message) from None
    await session.commit()
    return render(doctor, site, visit)
