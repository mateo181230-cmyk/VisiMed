"""Actual source and territory context. It never fabricates completed visits."""
from collections import Counter
from sqlalchemy import select
from uno import clock
from uno.modules.auth.permissions import representative_ids,line_ids,require_capability
from uno.modules.auth.models import User
from uno.modules.catalog.models import Doctor,Institution,Panel
from uno.modules.territory.models import PanelContact,LocationVerification,ReceptionAvailability,MedicalPotential,Pharmacy
from uno.modules.workflows.models import KnowledgeDocument

async def snapshot(session,actor):
 require_capability(actor,'dashboard.read')
 reps,lines=representative_ids(actor),line_ids(actor)
 rows=(await session.execute(select(PanelContact,Doctor,Institution)
  .join(Doctor,PanelContact.doctor_id==Doctor.id).join(Institution,PanelContact.institution_id==Institution.id)
  .join(Panel,(Panel.doctor_id==Doctor.id)&(Panel.representative_id==PanelContact.representative_id))
  .where(PanelContact.representative_id.in_(reps),Panel.default_line_id.in_(lines)))).all()
 users=(await session.scalars(select(User).where(User.id.in_(reps)))).all()
 sites={c.institution_id for c,d,s in rows}
 geo={x.institution_id:x for x in (await session.scalars(select(LocationVerification).where(LocationVerification.institution_id.in_(sites)))).all()}
 hours={(x.doctor_id,x.institution_id) for x in (await session.scalars(select(ReceptionAvailability).where(ReceptionAvailability.institution_id.in_(sites)))).all() if x.data.get('reception')}
 potentials=(await session.scalars(select(MedicalPotential).where(MedicalPotential.doctor_id.in_({c.doctor_id for c,d,s in rows})))).all()
 docs=(await session.execute(select(KnowledgeDocument.title,KnowledgeDocument.filename,KnowledgeDocument.status,KnowledgeDocument.slides).where(KnowledgeDocument.line_id.in_(lines)))).all()
 active=[r for r in rows if r[0].active]
 def verified(c):return c.institution_id in geo and geo[c.institution_id].status=='verified'
 specialties=Counter(d.specialty or 'Sin especialidad' for c,d,s in active)
 team=[]
 for u in users:
  own=[r for r in rows if r[0].representative_id==u.id];a=[r for r in own if r[0].active]
  team.append({'id':str(u.id),'name':u.full_name,'contacts':len(own),'active':len(a),'verified':sum(verified(c) for c,d,s in a),'hours':sum((c.doctor_id,c.institution_id) in hours for c,d,s in a)})
 points={str(s.id):{'id':str(s.id),'name':s.name,'lat':s.lat,'lng':s.lng} for c,d,s in active if verified(c) and s.lat is not None and s.lng is not None}
 pharmacies=(await session.scalars(select(Pharmacy).where(Pharmacy.representative_id.in_(reps),Pharmacy.active.is_(True)))).all()
 commercial=None
 if actor.management_profile=='line':
  from .commercial import summary
  commercial=await summary(session,actor)
 return {'as_of':clock.now().isoformat(),'label':'DATOS REALES IMPORTADOS','contacts':len(rows),'active_contacts':len(active),
  'doctors':len({c.doctor_id for c,d,s in rows}),'active_doctors':len({c.doctor_id for c,d,s in active}),
  'sites':len({c.institution_id for c,d,s in active}),'verified_sites':len(points),'pharmacies':len(pharmacies),
  'potential_profiles':len(potentials),'team':team,'points':list(points.values()),
  'specialties':[{'name':n,'value':v} for n,v in specialties.most_common()],
  'documents':[{'title':t,'filename':f,'status':s,'slides':len(sl)} for t,f,s,sl in docs],
  'commercial':commercial,'note':'El panel y los cortes conservan su origen. Los registros fuera del alcance de Bogotá permanecen inactivos; no generan visitas ni resultados del piloto.'}
