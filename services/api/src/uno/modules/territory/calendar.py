"""A unified read model; events keep the IDs of their original operational modules."""
from datetime import date, timedelta
import uuid
from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from uno.deps import get_current_user, get_session
from uno.modules.auth.permissions import representative_ids, require_representative, line_ids
from uno.modules.agenda.models import Visit
from uno.modules.catalog.models import Doctor, Institution
from uno.modules.marketing.dashboard import date_bounds
from uno.modules.marketing.models import MarketingActivity
from uno.modules.marketing.schemas import KINDS
from .models import PharmacyVisit, Pharmacy, RoutePlan

router = APIRouter(prefix="/v1/territory", tags=["calendar"])


@router.get("/calendar")
async def calendar(start: date, end: date, response: Response,
                   representative_id: uuid.UUID | None = None,
                   actor=Depends(get_current_user), session=Depends(get_session)):
    lo, hi = date_bounds(start, end)
    if representative_id: require_representative(actor, representative_id)
    reps = [representative_id] if representative_id else representative_ids(actor)
    lines = line_ids(actor)
    def scope(query, model):
        return query.where(model.representative_id.in_(reps)) if reps is not None else query
    vq = scope(select(Visit, Doctor.full_name, Institution.name, Institution.address, Institution.ref_source)
        .join(Doctor, Visit.doctor_id == Doctor.id).outerjoin(Institution, Visit.institution_id == Institution.id)
        .where(Visit.scheduled_at >= lo, Visit.scheduled_at < hi), Visit)
    mq = scope(select(MarketingActivity, Institution.name).join(Institution)
        .where(MarketingActivity.starts_at >= lo, MarketingActivity.starts_at < hi), MarketingActivity)
    if lines is not None:
        vq = vq.where(Visit.primary_line_id.in_(lines))
        mq = mq.where(MarketingActivity.line_id.in_(lines))
    events = []
    for v, name, site, address, source in (await session.execute(vq)).all():
        events.append(dict(id=str(v.id), kind="medical", title=name, site=site, address=address,
            starts_at=v.scheduled_at.isoformat(), ends_at=(v.scheduled_at+timedelta(minutes=20)).isoformat(),
            duration_estimated=True, status=v.status, representative_id=str(v.representative_id),
            automatic=v.planned_by == "routing", demo=v.planned_by == "demo" or source in ('demo','demo_copy'),
            prepare_href="/territorio/?module=brief&visit="+str(v.id),
            href="/territorio/?module=demo" if source == "demo" and not v.finished_at and actor.role == "rep" else
                 ("/territorio/?report="+str(v.id) if v.status=='confirmed' or actor.role!='rep' else "/visitas/"+str(v.id))))
    pq = scope(select(PharmacyVisit, Institution.name, Institution.address)
        .join(Pharmacy, PharmacyVisit.pharmacy_id == Pharmacy.id)
        .join(Institution, Pharmacy.institution_id == Institution.id)
        .where(PharmacyVisit.scheduled_at >= lo, PharmacyVisit.scheduled_at < hi), PharmacyVisit)
    for v, name, address in (await session.execute(pq)).all():
        events.append(dict(id=str(v.id), kind="pharmacy", title=name, site=name, address=address,
            starts_at=v.scheduled_at.isoformat(), ends_at=(v.scheduled_at+timedelta(minutes=20)).isoformat(),
            duration_estimated=True, status=v.status, representative_id=str(v.representative_id),
            demo=v.planned_by=='demo',
            href="/territorio/?tab=pharmacy&rep="+str(v.representative_id)))
    for a, site in (await session.execute(mq)).all():
        events.append(dict(id=str(a.id), kind="marketing", title=KINDS[a.kind], site=site,
            starts_at=a.starts_at.isoformat(), ends_at=a.ends_at.isoformat(), duration_estimated=False,
            status=a.status, representative_id=str(a.representative_id),
            demo=bool(a.data.get('demo')),
            href="/territorio/?module=marketing&activity="+str(a.id)))
    response.headers["Cache-Control"] = "private, no-store"
    return {"start":str(start), "end":str(end), "timezone":"America/Bogota",
            "events":sorted(events,key=lambda e:e["starts_at"])}
