"""Bajada incremental de estado del visitador (doc 01 §10.6; doc 02 T1.5).

El teléfono pide ``GET /v1/me/state?cursor=N`` y recibe solo lo que cambió después de ``N``.
Sin cursor (o con un cursor mayor que el del servidor, por ejemplo tras reiniciar la base) se
entrega el estado completo: catálogo de líneas, panel de médicos y visitas de −7 a +14 días.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.db import current_change_seq
from uno.modules.agenda.models import Visit, VisitLine
from uno.modules.auth.models import User
from uno.modules.calls.models import Call, CallVisit, VisitReport
from uno.modules.catalog.models import Doctor, Institution, Panel, Product, ProductLine
from uno.modules.notifications.models import REMIND_OPTIONS

WINDOW_PAST_DAYS = 7
WINDOW_FUTURE_DAYS = 14


class LineOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    active: bool


class ProductOut(BaseModel):
    id: uuid.UUID
    line_id: uuid.UUID
    name: str
    active: bool


class InstitutionOut(BaseModel):
    id: uuid.UUID
    name: str
    address: str | None
    city: str | None
    lat: float | None
    lng: float | None
    radius_m: int


class DoctorOut(BaseModel):
    id: uuid.UUID
    full_name: str
    specialty: str | None
    institution_id: uuid.UUID | None
    review_state: str
    default_line_id: uuid.UUID | None


class GeoOut(BaseModel):
    """Resultado de geocerca de un momento («Llegué» o «Terminé»). Sin coordenadas: el teléfono
    ya las tiene y no hace falta devolverlas."""

    state: str  # verificada | lejos | imprecisa | sin_referencia | sin_gps
    distance_m: int | None
    precision_m: float | None


class CallInfoOut(BaseModel):
    """La llamada de resumen de esta visita mientras sigue viva (por marcar o en curso)."""

    status: str  # queued | dialing
    attempt: int  # veces que ya se marcó
    next_at: datetime | None  # cuándo vuelve a marcar (si está por marcar)
    reason: str | None  # por qué no salió la última vez (no_answer, busy, voicemail…)


class VisitOut(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    institution_id: uuid.UUID | None
    primary_line_id: uuid.UUID
    line_ids: list[uuid.UUID]
    scheduled_at: datetime
    status: str
    planned_by: str
    not_done_reason: str | None
    arrived_at: datetime | None
    finished_at: datetime | None
    arrival_geo: GeoOut | None  # None mientras no haya «Llegué»
    finish_geo: GeoOut | None  # None mientras no haya «Terminé»
    updated_at: datetime
    call: CallInfoOut | None = None


class ReportFieldOut(BaseModel):
    value: str | int | bool | None
    confidence: str  # high | medium | low
    source: str  # call | rep_edit


class ReportOut(BaseModel):
    """La ficha de una visita: lo que contó el visitador en la llamada, con su confianza."""

    visit_id: uuid.UUID
    status: str  # ready | confirmed
    complete: bool
    fields: dict[str, ReportFieldOut]
    confirmed_at: datetime | None
    updated_at: datetime


class StateConfig(BaseModel):
    reminder_options: list[int]
    window_past_days: int = WINDOW_PAST_DAYS
    window_future_days: int = WINDOW_FUTURE_DAYS


class StateOut(BaseModel):
    server_time: datetime
    cursor: int
    full: bool
    timezone: str
    lines: list[LineOut]
    products: list[ProductOut]
    institutions: list[InstitutionOut]
    doctors: list[DoctorOut]
    visits: list[VisitOut]
    reports: list[ReportOut]
    config: StateConfig


def _geo_out(state: str | None, distance_m: int | None, precision_m: float | None) -> GeoOut | None:
    return (
        None
        if state is None
        else GeoOut(state=state, distance_m=distance_m, precision_m=precision_m)
    )


def _window(now: datetime, tz_name: str) -> tuple[datetime, datetime]:
    today: date = clock.local_date(now, tz_name)
    start, _ = clock.local_day_bounds(today - timedelta(days=WINDOW_PAST_DAYS), tz_name)
    _, end = clock.local_day_bounds(today + timedelta(days=WINDOW_FUTURE_DAYS), tz_name)
    return start, end


async def build_state(
    session: AsyncSession, user: User, cursor: int | None, now: datetime
) -> StateOut:
    current = await current_change_seq(session)
    full = cursor is None or cursor <= 0 or cursor > current
    since = 0 if full else int(cursor or 0)

    lines = (await session.execute(select(ProductLine).order_by(ProductLine.code))).scalars().all()
    products = (await session.execute(select(Product).order_by(Product.name))).scalars().all()

    # --- médicos del panel que cambiaron (o cuyo vínculo con el panel cambió)
    doctor_rows = (
        await session.execute(
            select(Doctor, Panel.default_line_id)
            .join(Panel, Panel.doctor_id == Doctor.id)
            .where(
                Panel.representative_id == user.id,
                or_(Doctor.change_seq > since, Panel.change_seq > since),
            )
            .order_by(Doctor.full_name)
        )
    ).all()
    doctors = [
        DoctorOut(
            id=d.id,
            full_name=d.full_name,
            specialty=d.specialty,
            institution_id=d.institution_id,
            review_state=d.review_state,
            default_line_id=default_line_id,
        )
        for d, default_line_id in doctor_rows
    ]

    # --- instituciones: las de sus médicos que cambiaron, más las de los médicos devueltos
    returned_inst_ids = {d.institution_id for d in doctors if d.institution_id is not None}
    panel_inst_ids = (
        select(Doctor.institution_id)
        .join(Panel, Panel.doctor_id == Doctor.id)
        .where(Panel.representative_id == user.id, Doctor.institution_id.is_not(None))
    )
    inst_query = select(Institution).where(
        Institution.id.in_(panel_inst_ids),
        or_(
            Institution.change_seq > since,
            Institution.id.in_(returned_inst_ids or {uuid.UUID(int=0)}),
        ),
    )
    institutions = (await session.execute(inst_query.order_by(Institution.name))).scalars().all()

    # --- visitas
    visit_query = select(Visit).where(Visit.representative_id == user.id, Visit.change_seq > since)
    if full:
        start, end = _window(now, user.timezone)
        visit_query = visit_query.where(Visit.scheduled_at >= start, Visit.scheduled_at < end)
    visits = (await session.execute(visit_query.order_by(Visit.scheduled_at))).scalars().all()

    line_map: dict[uuid.UUID, list[uuid.UUID]] = {v.id: [v.primary_line_id] for v in visits}
    if visits:
        vl_rows = (
            (
                await session.execute(
                    select(VisitLine).where(
                        VisitLine.visit_id.in_(list(line_map)), VisitLine.role == "planned"
                    )
                )
            )
            .scalars()
            .all()
        )
        for vl in vl_rows:
            ids = line_map[vl.visit_id]
            if vl.line_id not in ids:
                ids.append(vl.line_id)

    # --- llamadas vivas de esas visitas (para «te llamamos de nuevo a las…»)
    live_calls: dict[uuid.UUID, CallInfoOut] = {}
    if visits:
        rows = (
            await session.execute(
                select(
                    CallVisit.visit_id,
                    Call.status,
                    Call.attempt,
                    Call.scheduled_for,
                    Call.failure_reason,
                )
                .join(Call, Call.id == CallVisit.call_id)
                .where(CallVisit.visit_id.in_([v.id for v in visits]), CallVisit.live.is_(True))
            )
        ).all()
        for visit_id, status, attempt, scheduled_for, reason in rows:
            live_calls[visit_id] = CallInfoOut(
                status=status,
                attempt=attempt,
                next_at=scheduled_for if status == "queued" and attempt > 0 else None,
                reason=reason,
            )

    # --- fichas (resúmenes de la llamada) de sus visitas
    report_query = (
        select(VisitReport)
        .join(Visit, Visit.id == VisitReport.visit_id)
        .where(Visit.representative_id == user.id, VisitReport.change_seq > since)
    )
    if full:
        start, end = _window(now, user.timezone)
        report_query = report_query.where(Visit.scheduled_at >= start, Visit.scheduled_at < end)
    reports = (await session.execute(report_query.order_by(VisitReport.updated_at))).scalars().all()

    return StateOut(
        server_time=now,
        cursor=current,
        full=full,
        timezone=user.timezone,
        lines=[LineOut(id=x.id, code=x.code, name=x.name, active=x.active) for x in lines],
        products=[
            ProductOut(id=x.id, line_id=x.line_id, name=x.name, active=x.active) for x in products
        ],
        institutions=[
            InstitutionOut(
                id=x.id,
                name=x.name,
                address=x.address,
                city=x.city,
                lat=x.lat,
                lng=x.lng,
                radius_m=x.radius_m,
            )
            for x in institutions
        ],
        doctors=doctors,
        visits=[
            VisitOut(
                id=v.id,
                doctor_id=v.doctor_id,
                institution_id=v.institution_id,
                primary_line_id=v.primary_line_id,
                line_ids=line_map[v.id],
                scheduled_at=v.scheduled_at,
                status=v.status,
                planned_by=v.planned_by,
                not_done_reason=v.not_done_reason,
                arrived_at=v.arrived_at,
                finished_at=v.finished_at,
                arrival_geo=_geo_out(
                    v.arrival_geo_state, v.arrival_distance_m, v.arrival_precision_m
                ),
                finish_geo=_geo_out(v.finish_geo_state, v.finish_distance_m, v.finish_precision_m),
                updated_at=v.updated_at,
                call=live_calls.get(v.id),
            )
            for v in visits
        ],
        reports=[
            ReportOut(
                visit_id=r.visit_id,
                status=r.status,
                complete=r.complete,
                fields={
                    name: ReportFieldOut(**entry)
                    for name, entry in (r.fields or {}).items()
                    if isinstance(entry, dict) and entry.get("value") is not None
                },
                confirmed_at=r.confirmed_at,
                updated_at=r.updated_at,
            )
            for r in reports
        ],
        config=StateConfig(reminder_options=list(REMIND_OPTIONS)),
    )
