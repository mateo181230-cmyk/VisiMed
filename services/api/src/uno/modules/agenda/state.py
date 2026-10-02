"""Bajada incremental de estado del visitador (doc 01 §10.6; doc 02 T1.5).

El teléfono pide ``GET /v1/me/state?cursor=N`` y recibe solo lo que cambió después de ``N``.
Sin cursor (o con un cursor mayor que el del servidor, por ejemplo tras reiniciar la base) se
entrega el estado completo: catálogo, panel, todas sus visitas y reportes, con los médicos e
instituciones que referencian. La ventana de configuración solo orienta la presentación.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from uno.db import current_change_seq
from uno.modules.agenda.models import Visit, VisitLine
from uno.modules.auth.models import User
from uno.modules.calls.models import Call, CallVisit, VisitReport
from uno.modules.calls.schema import missing_report_fields
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
    title: str | None = None
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
    report_notified_at: datetime | None = None
    report_due_at: datetime | None = None
    report_invalid_at: datetime | None = None
    report_mode: str | None = None
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
    # Compatibilidad con clientes previos: sugerencia visual, nunca límite de sincronización.
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


async def build_state(
    session: AsyncSession, user: User, cursor: int | None, now: datetime
) -> StateOut:
    current = await current_change_seq(session)
    full = cursor is None or cursor <= 0 or cursor > current
    since = 0 if full else int(cursor or 0)

    lines = (await session.execute(select(ProductLine).order_by(ProductLine.code))).scalars().all()
    products = (await session.execute(select(Product).order_by(Product.name))).scalars().all()

    # --- visitas: full reemplaza la copia local y debe conservar historia y agenda futura.
    visit_query = select(Visit).where(Visit.representative_id == user.id)
    if not full:
        visit_query = visit_query.where(Visit.change_seq > since)
    visits = (await session.execute(visit_query.order_by(Visit.scheduled_at))).scalars().all()

    # --- panel actual más médicos históricos; las visitas nuevas incluyen sus dependencias.
    panel_doctor_ids = select(Panel.doctor_id).where(Panel.representative_id == user.id)
    visit_doctor_ids = select(Visit.doctor_id).where(Visit.representative_id == user.id)
    accessible_doctor = or_(Doctor.id.in_(panel_doctor_ids), Doctor.id.in_(visit_doctor_ids))
    doctor_query = (
        select(Doctor, Panel.default_line_id)
        .outerjoin(
            Panel,
            and_(Panel.doctor_id == Doctor.id, Panel.representative_id == user.id),
        )
        .where(accessible_doctor)
    )
    if not full:
        doctor_query = doctor_query.where(
            or_(
                Doctor.change_seq > since,
                Panel.change_seq > since,
                Doctor.id.in_({v.doctor_id for v in visits}),
            )
        )
    doctor_rows = (await session.execute(doctor_query.order_by(Doctor.full_name))).all()
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

    # --- sedes actuales y sedes originales de las visitas, aunque el médico haya cambiado.
    returned_inst_ids = {d.institution_id for d in doctors if d.institution_id is not None} | {
        v.institution_id for v in visits if v.institution_id is not None
    }
    doctor_inst_ids = select(Doctor.institution_id).where(
        accessible_doctor, Doctor.institution_id.is_not(None)
    )
    visit_inst_ids = select(Visit.institution_id).where(
        Visit.representative_id == user.id, Visit.institution_id.is_not(None)
    )
    inst_query = select(Institution).where(
        or_(Institution.id.in_(doctor_inst_ids), Institution.id.in_(visit_inst_ids))
    )
    if not full:
        inst_query = inst_query.where(
            or_(Institution.change_seq > since, Institution.id.in_(returned_inst_ids))
        )
    institutions = (await session.execute(inst_query.order_by(Institution.name))).scalars().all()

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
                .where(
                    CallVisit.visit_id.in_([v.id for v in visits]),
                    CallVisit.live.is_(True),
                    Call.purpose != "reminder",
                )
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
        .where(Visit.representative_id == user.id)
    )
    if not full:
        report_query = report_query.where(VisitReport.change_seq > since)
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
                title=v.title,
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
                report_notified_at=v.report_notified_at,
                report_due_at=v.report_due_at,
                report_invalid_at=v.report_invalid_at,
                report_mode=v.report_mode,
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
                complete=not missing_report_fields(r.fields or {}),
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
