"""Lectura del piloto: historial y evidencia autorizada para la inteligencia.

La ventana de consulta es explícita y las coordenadas no salen en este contrato.
Un visitador recibe solo su panel y sus visitas; gerencia recibe el equipo.
No consulta ni simula una conexión a ESOMED.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.deps import get_current_user, get_session
from uno.modules.agenda.models import Visit, VisitLine
from uno.modules.agenda.state import LineOut, ReportFieldOut, ReportOut
from uno.modules.auth.models import User
from uno.modules.auth.permissions import line_ids, representative_ids
from uno.modules.calls.models import VisitReport
from uno.modules.calls.schema import missing_report_fields
from uno.modules.catalog.models import Doctor, Institution, Panel, ProductLine

router = APIRouter(prefix="/v1/intelligence", tags=["intelligence"])


class PilotRepresentative(BaseModel):
    id: uuid.UUID
    name: str


class PilotDoctor(BaseModel):
    id: uuid.UUID
    name: str
    specialty: str | None
    institution: str | None
    address: str | None
    zone: str | None
    representative_id: uuid.UUID
    default_line_id: uuid.UUID | None
    review_state: str


class PilotVisit(BaseModel):
    title: str | None = None
    id: uuid.UUID
    doctor_id: uuid.UUID
    representative_id: uuid.UUID
    primary_line_id: uuid.UUID
    discussed_line_ids: list[uuid.UUID] = Field(default_factory=list)
    scheduled_at: datetime
    status: str
    arrived_at: datetime | None
    finished_at: datetime | None
    arrival_geo_state: str | None
    finish_geo_state: str | None


class PilotSnapshot(BaseModel):
    now: datetime
    timezone: str
    history_since: datetime
    representatives: list[PilotRepresentative]
    doctors: list[PilotDoctor]
    lines: list[LineOut]
    visits: list[PilotVisit]
    reports: list[ReportOut]
    esomed_connected: bool = False


@router.get("/snapshot", response_model=PilotSnapshot)
async def snapshot(
    history_days: int = Query(default=365, ge=1, le=365),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PilotSnapshot:
    now = clock.now()
    since = now - timedelta(days=history_days)
    allowed = representative_ids(user)
    query = select(Visit).where(Visit.scheduled_at >= since)
    if allowed is not None:
        query = query.where(Visit.representative_id.in_(allowed))
    visits = (await session.scalars(query.order_by(Visit.scheduled_at))).all()
    visit_ids = [v.id for v in visits]
    doctor_ids = {v.doctor_id for v in visits}
    panel_query = select(Panel)
    if allowed is not None:
        panel_query = panel_query.where(Panel.representative_id.in_(allowed))
    panel = (await session.scalars(panel_query)).all()
    doctor_ids.update(p.doctor_id for p in panel)
    doctor_rows = (
        await session.execute(
            select(Doctor, Institution)
            .outerjoin(Institution, Doctor.institution_id == Institution.id)
            .where(Doctor.id.in_(doctor_ids))
            .order_by(Doctor.full_name)
        )
    ).all()
    assignments = {p.doctor_id: (p.representative_id, p.default_line_id) for p in panel}
    for visit in reversed(visits):
        assignments.setdefault(visit.doctor_id, (visit.representative_id, visit.primary_line_id))
    rep_ids = {v.representative_id for v in visits} | {p.representative_id for p in panel}
    if allowed is not None:
        rep_query = select(User).where(User.id.in_(allowed))
    elif user.role in ("admin", "manager"):
        rep_query = select(User).where(or_(User.id.in_(rep_ids), User.role == "rep"))
    else:
        rep_query = select(User).where(User.id == user.id)
    reps = (await session.scalars(rep_query.order_by(User.full_name))).all()
    lines = (await session.scalars(select(ProductLine).order_by(ProductLine.code))).all()
    allowed_lines = line_ids(user)
    if allowed_lines is not None:
        lines = [x for x in lines if x.id in allowed_lines]
    reports = (
        await session.scalars(select(VisitReport).where(VisitReport.visit_id.in_(visit_ids)))
    ).all()
    discussed: dict[uuid.UUID, list[uuid.UUID]] = {}
    for row in (
        await session.scalars(
            select(VisitLine)
            .where(VisitLine.visit_id.in_(visit_ids), VisitLine.role == "discussed")
            .order_by(VisitLine.line_id)
        )
    ).all():
        discussed.setdefault(row.visit_id, []).append(row.line_id)
    return PilotSnapshot(
        now=now,
        timezone=user.timezone,
        history_since=since,
        representatives=[PilotRepresentative(id=r.id, name=r.full_name) for r in reps],
        doctors=[
            PilotDoctor(
                id=d.id,
                name=d.full_name,
                specialty=d.specialty,
                institution=i.name if i else None,
                address=i.address if i else None,
                zone=i.city if i else None,
                representative_id=assignments[d.id][0],
                default_line_id=assignments[d.id][1],
                review_state=d.review_state,
            )
            for d, i in doctor_rows
        ],
        lines=[
            LineOut(id=line.id, code=line.code, name=line.name, active=line.active)
            for line in lines
        ],
        visits=[
            PilotVisit(
                title=v.title,
                id=v.id,
                doctor_id=v.doctor_id,
                representative_id=v.representative_id,
                primary_line_id=v.primary_line_id,
                discussed_line_ids=discussed.get(v.id, []),
                scheduled_at=v.scheduled_at,
                status=v.status,
                arrived_at=v.arrived_at,
                finished_at=v.finished_at,
                arrival_geo_state=v.arrival_geo_state,
                finish_geo_state=v.finish_geo_state,
            )
            for v in visits
        ],
        reports=[
            ReportOut(
                visit_id=r.visit_id,
                status=r.status,
                complete=not missing_report_fields(r.fields or {}),
                confirmed_at=r.confirmed_at,
                updated_at=r.updated_at,
                fields={
                    k: ReportFieldOut(**v)
                    for k, v in (r.fields or {}).items()
                    if isinstance(v, dict) and v.get("value") is not None
                },
            )
            for r in reports
        ],
    )
