"""Manejadores de eventos de la agenda (doc 01 §10.2, §11; doc 03 §5.2).

Eventos: ``doctor_created``, ``visit_scheduled``, ``visit_rescheduled``, ``visit_not_done``,
``visit_arrived``, ``visit_finished`` y ``visit_location_retried``.
Cada manejador es idempotente por entidad: reenviar el mismo hecho no cambia el resultado.
Cada cambio emite su evento de dominio en la misma transacción.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uno import events
from uno.db import next_change_seq
from uno.modules.agenda import geofence
from uno.modules.agenda.models import Visit, VisitLine
from uno.modules.catalog.models import Doctor, Institution, Panel, ProductLine
from uno.modules.sync.registry import EventContext, Rejected, handles

MAX_PAST = timedelta(days=366 * 2)
MAX_FUTURE = timedelta(days=366 * 2)

# «Reintentar ubicación»: hasta 2 min después del toque se puede reemplazar una lectura pobre.
RETRY_WINDOW = timedelta(minutes=2)
MAX_ERROR_LEN = 120  # el diagnóstico `error` es corto; si el teléfono manda más, se recorta


# --------------------------------------------------------------------- utilidades


async def _panel_row(ctx: EventContext, doctor_id: uuid.UUID) -> Panel | None:
    return (
        await ctx.session.execute(
            select(Panel).where(
                Panel.representative_id == ctx.user.id, Panel.doctor_id == doctor_id
            )
        )
    ).scalar_one_or_none()


async def _active_lines(ctx: EventContext, line_ids: list[uuid.UUID]) -> list[ProductLine]:
    rows = (
        (
            await ctx.session.execute(
                select(ProductLine).where(
                    ProductLine.id.in_(line_ids), ProductLine.active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {r.id: r for r in rows}
    if len(by_id) != len(set(line_ids)):
        raise Rejected("unknown_line")
    return [by_id[i] for i in line_ids]


def _check_time(ctx: EventContext, scheduled_at: AwareDatetime) -> None:
    if scheduled_at < ctx.now - MAX_PAST or scheduled_at > ctx.now + MAX_FUTURE:
        raise Rejected("invalid_time")


async def _own_visit(ctx: EventContext) -> Visit:
    if ctx.visit_id is None:
        raise Rejected("visit_id_required")
    visit = await ctx.session.get(Visit, ctx.visit_id)
    if visit is None or visit.representative_id != ctx.user.id:
        raise Rejected("unknown_visit")
    return visit


# --------------------------------------------------------------------- doctor_created


class InstitutionIn(BaseModel):
    id: uuid.UUID
    name: str = Field(min_length=2, max_length=160)
    address: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=80)


class DoctorCreatedPayload(BaseModel):
    doctor_id: uuid.UUID
    full_name: str = Field(min_length=2, max_length=160)
    specialty: str | None = Field(default=None, max_length=80)
    default_line_id: uuid.UUID
    institution_id: uuid.UUID | None = None  # institución que el teléfono ya conoce
    institution: InstitutionIn | None = None  # o una institución nueva


@handles("doctor_created", DoctorCreatedPayload)
async def doctor_created(ctx: EventContext, p: DoctorCreatedPayload) -> None:
    session = ctx.session
    if p.institution_id is not None and p.institution is not None:
        raise Rejected("institution_ambiguous")

    existing = await session.get(Doctor, p.doctor_id)
    if existing is not None:
        # Mismo médico reenviado con otro event_id: idempotente si ya es del visitador.
        if await _panel_row(ctx, p.doctor_id) is not None:
            return
        raise Rejected("doctor_id_conflict")

    (line,) = await _active_lines(ctx, [p.default_line_id])

    institution_id = p.institution_id
    if p.institution is not None:
        inst = await session.get(Institution, p.institution.id)
        if inst is None:
            inst = Institution(
                id=p.institution.id,
                name=p.institution.name.strip(),
                address=(p.institution.address or "").strip() or None,
                city=(p.institution.city or "").strip() or None,
                created_by=ctx.user.id,
                created_at=ctx.now,
                change_seq=await next_change_seq(session),
            )
            session.add(inst)
        institution_id = inst.id
    elif institution_id is not None and await session.get(Institution, institution_id) is None:
        raise Rejected("unknown_institution")

    doctor = Doctor(
        id=p.doctor_id,
        full_name=p.full_name.strip(),
        specialty=(p.specialty or "").strip() or None,
        institution_id=institution_id,
        review_state="pending_review",
        created_by=ctx.user.id,
        created_at=ctx.now,
        change_seq=await next_change_seq(session),
    )
    session.add(doctor)
    await session.flush()
    session.add(
        Panel(
            representative_id=ctx.user.id,
            doctor_id=doctor.id,
            default_line_id=line.id,
            change_seq=await next_change_seq(session),
        )
    )
    await events.emit(
        session,
        event_type="doctor_created",
        occurred_at=ctx.occurred_at,
        recorded_at=ctx.now,
        actor_type="representative",
        actor_id=ctx.user.id,
        entities={
            "doctor_id": doctor.id,
            "institution_id": institution_id,
            "representative_id": ctx.user.id,
            "product_line_ids": [line.id],
        },
        payload={"specialty_present": doctor.specialty is not None},
        correlation_id=doctor.id,
        causation_id=ctx.event_id,
    )


# --------------------------------------------------------------------- visit_scheduled


class VisitScheduledPayload(BaseModel):
    doctor_id: uuid.UUID
    line_ids: list[uuid.UUID] = Field(min_length=1, max_length=2)
    scheduled_at: AwareDatetime
    planned_by: Literal["rep", "spontaneous"] = "rep"
    suggestion_id: uuid.UUID | None = None


@handles("visit_scheduled", VisitScheduledPayload)
async def visit_scheduled(ctx: EventContext, p: VisitScheduledPayload) -> None:
    session = ctx.session
    if ctx.visit_id is None:
        raise Rejected("visit_id_required")
    if len(set(p.line_ids)) != len(p.line_ids):
        raise Rejected("duplicate_line")
    _check_time(ctx, p.scheduled_at)

    doctor = await session.get(Doctor, p.doctor_id)
    if doctor is None or await _panel_row(ctx, p.doctor_id) is None:
        raise Rejected("unknown_doctor")
    lines = await _active_lines(ctx, p.line_ids)

    existing = await session.get(Visit, ctx.visit_id)
    if existing is not None:
        same = (
            existing.representative_id == ctx.user.id
            and existing.doctor_id == p.doctor_id
            and existing.primary_line_id == lines[0].id
            and existing.scheduled_at == p.scheduled_at
        )
        if same:
            return
        raise Rejected("visit_id_conflict")

    visit = Visit(
        id=ctx.visit_id,
        representative_id=ctx.user.id,
        doctor_id=doctor.id,
        institution_id=doctor.institution_id,
        primary_line_id=lines[0].id,
        scheduled_at=p.scheduled_at,
        status="scheduled",
        planned_by=p.planned_by,
        suggestion_id=p.suggestion_id,
        device_id=ctx.device_id,
        created_at=ctx.now,
        updated_at=ctx.now,
        change_seq=await next_change_seq(session),
    )
    session.add(visit)
    await session.flush()
    for line in lines:
        session.add(VisitLine(visit_id=visit.id, line_id=line.id, role="planned", source="agenda"))
    await events.emit(
        session,
        event_type="visit_scheduled",
        occurred_at=ctx.occurred_at,
        recorded_at=ctx.now,
        actor_type="representative",
        actor_id=ctx.user.id,
        entities={
            "visit_id": visit.id,
            "doctor_id": doctor.id,
            "institution_id": doctor.institution_id,
            "representative_id": ctx.user.id,
            "product_line_ids": [line.id for line in lines],
        },
        payload={
            "scheduled_at": p.scheduled_at,
            "planned_by": p.planned_by,
            "suggestion_id": p.suggestion_id,
        },
        correlation_id=visit.id,
        causation_id=ctx.event_id,
    )


# --------------------------------------------------------------------- visit_rescheduled


class VisitRescheduledPayload(BaseModel):
    scheduled_at: AwareDatetime


@handles("visit_rescheduled", VisitRescheduledPayload)
async def visit_rescheduled(ctx: EventContext, p: VisitRescheduledPayload) -> None:
    visit = await _own_visit(ctx)
    _check_time(ctx, p.scheduled_at)
    if visit.status != "scheduled":
        # La evidencia de una visita ya iniciada es inmutable (doc 01 §10.7).
        raise Rejected("visit_not_editable")
    if visit.scheduled_at == p.scheduled_at:
        return
    previous = visit.scheduled_at
    visit.scheduled_at = p.scheduled_at
    visit.reschedule_count += 1
    visit.updated_at = ctx.now
    visit.change_seq = await next_change_seq(ctx.session)
    await events.emit(
        ctx.session,
        event_type="visit_rescheduled",
        occurred_at=ctx.occurred_at,
        recorded_at=ctx.now,
        actor_type="representative",
        actor_id=ctx.user.id,
        entities={
            "visit_id": visit.id,
            "doctor_id": visit.doctor_id,
            "institution_id": visit.institution_id,
            "representative_id": ctx.user.id,
            "product_line_ids": [visit.primary_line_id],
        },
        payload={"scheduled_at": p.scheduled_at, "previous_scheduled_at": previous},
        correlation_id=visit.id,
        causation_id=ctx.event_id,
    )


# --------------------------------------------------------------------- visit_not_done


class VisitNotDonePayload(BaseModel):
    reason: Literal["doctor_unavailable", "cancelled_by_office", "rescheduled", "other"]


@handles("visit_not_done", VisitNotDonePayload)
async def visit_not_done(ctx: EventContext, p: VisitNotDonePayload) -> None:
    visit = await _own_visit(ctx)
    if visit.status == "not_done":
        if visit.not_done_reason == p.reason:
            return
        raise Rejected("visit_not_editable")
    if visit.status != "scheduled":
        raise Rejected("visit_not_editable")
    visit.status = "not_done"
    visit.not_done_reason = p.reason
    visit.updated_at = ctx.now
    visit.change_seq = await next_change_seq(ctx.session)
    await events.emit(
        ctx.session,
        event_type="visit_not_done",
        occurred_at=ctx.occurred_at,
        recorded_at=ctx.now,
        actor_type="representative",
        actor_id=ctx.user.id,
        entities={
            "visit_id": visit.id,
            "doctor_id": visit.doctor_id,
            "institution_id": visit.institution_id,
            "representative_id": ctx.user.id,
            "product_line_ids": [visit.primary_line_id],
        },
        payload={"reason": p.reason},
        correlation_id=visit.id,
        causation_id=ctx.event_id,
    )


# --------------------------------------------------------------------- llegué / terminé (E4)


class Location(BaseModel):
    """Una lectura de ubicación del teléfono. ``source="reused"`` la copió de otra llegada."""

    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    precision_m: float = Field(ge=0, allow_inf_nan=False)
    fix_ts: AwareDatetime
    source: Literal["gps", "reused"]


class _Diagnostics(BaseModel):
    """Diagnóstico del intento de leer la ubicación. Va solo a la bitácora de dominio."""

    permission: Literal["granted", "denied", "prompt"] | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class VisitTouchPayload(_Diagnostics):
    """Payload de ``visit_arrived`` y ``visit_finished``. Sin lectura, ``location`` es ``null``:
    la visita nunca se pierde por falta de GPS, queda en estado ``sin_gps``."""

    location: Location | None = None
    error: str | None = None

    @field_validator("error", mode="before")
    @classmethod
    def _shorten_error(cls, value: Any) -> Any:
        # Un texto de diagnóstico largo nunca debe costar la visita: se recorta en vez de rechazar.
        return value[:MAX_ERROR_LEN] if isinstance(value, str) else value


class VisitLocationRetriedPayload(_Diagnostics):
    moment: Literal["arrival", "finish"]
    location: Location  # obligatoria: reintentar sin lectura no tiene sentido


async def _classify_for_visit(
    session: AsyncSession, visit: Visit, location: Location | None
) -> tuple[str, int | None]:
    """Estado de geocerca contra la referencia de la institución de la visita (si la tiene)."""
    reference: geofence.Reference | None = None
    radius_m = 0
    if visit.institution_id is not None:
        institution = await session.get(Institution, visit.institution_id)
        if institution is not None and institution.lat is not None and institution.lng is not None:
            reference = geofence.Reference(institution.lat, institution.lng)
            radius_m = institution.radius_m
    reading = (
        geofence.Reading(location.lat, location.lng, location.precision_m)
        if location is not None
        else None
    )
    return geofence.classify(reading, reference, radius_m)


def _write_geo(
    visit: Visit, prefix: str, location: Location | None, state: str, distance_m: int | None
) -> None:
    """Guarda la lectura y su estado en las columnas ``arrival_*`` o ``finish_*`` (``prefix``)."""
    setattr(visit, f"{prefix}_fix_ts", location.fix_ts if location else None)
    setattr(visit, f"{prefix}_lat", location.lat if location else None)
    setattr(visit, f"{prefix}_lng", location.lng if location else None)
    setattr(visit, f"{prefix}_precision_m", location.precision_m if location else None)
    setattr(visit, f"{prefix}_source", location.source if location else None)
    setattr(visit, f"{prefix}_geo_state", state)
    setattr(visit, f"{prefix}_distance_m", distance_m)


def _geo_payload(location: Location | None, state: str, distance_m: int | None) -> dict[str, Any]:
    """Parte geográfica del evento de dominio. **Sin lat/lng**: la política de la bitácora
    (``events.FORBIDDEN_KEYS``) no admite coordenadas; ellas viven solo en la tabla ``visit``."""
    return {
        "geo_state": state,
        "distance_m": distance_m,
        "precision_m": location.precision_m if location else None,
        "location_source": location.source if location else None,
        "fix_ts": location.fix_ts if location else None,
    }


async def _emit_visit_event(
    ctx: EventContext, visit: Visit, event_type: str, payload: dict[str, Any]
) -> None:
    await events.emit(
        ctx.session,
        event_type=event_type,
        occurred_at=ctx.occurred_at,
        recorded_at=ctx.now,
        actor_type="representative",
        actor_id=ctx.user.id,
        entities={
            "visit_id": visit.id,
            "doctor_id": visit.doctor_id,
            "institution_id": visit.institution_id,
            "representative_id": ctx.user.id,
            "product_line_ids": [visit.primary_line_id],
        },
        payload=payload,
        correlation_id=visit.id,
        causation_id=ctx.event_id,
    )


@handles("visit_arrived", VisitTouchPayload)
async def visit_arrived(ctx: EventContext, p: VisitTouchPayload) -> None:
    visit = await _own_visit(ctx)
    if visit.status != "scheduled":
        raise Rejected("visit_not_editable")
    state, distance_m = await _classify_for_visit(ctx.session, visit, p.location)
    visit.status = "in_progress"
    visit.arrived_at = ctx.occurred_at  # hora del toque en el teléfono
    _write_geo(visit, "arrival", p.location, state, distance_m)
    visit.updated_at = ctx.now
    visit.change_seq = await next_change_seq(ctx.session)
    await _emit_visit_event(
        ctx,
        visit,
        "visit_arrived",
        {
            **_geo_payload(p.location, state, distance_m),
            "permission": p.permission,
            "duration_ms": p.duration_ms,
            "error": p.error,
        },
    )


@handles("visit_finished", VisitTouchPayload)
async def visit_finished(ctx: EventContext, p: VisitTouchPayload) -> None:
    visit = await _own_visit(ctx)
    if visit.status not in ("scheduled", "in_progress"):
        raise Rejected("visit_not_editable")
    # «Terminé» sin «Llegué»: la visita queda finished con arrived_at nulo (esa es la señal).
    without_arrival = visit.status == "scheduled"
    state, distance_m = await _classify_for_visit(ctx.session, visit, p.location)
    visit.status = "finished"
    visit.finished_at = ctx.occurred_at
    _write_geo(visit, "finish", p.location, state, distance_m)
    visit.updated_at = ctx.now
    visit.change_seq = await next_change_seq(ctx.session)
    await _emit_visit_event(
        ctx,
        visit,
        "visit_finished",
        {
            **_geo_payload(p.location, state, distance_m),
            "permission": p.permission,
            "duration_ms": p.duration_ms,
            "error": p.error,
            "without_arrival": without_arrival,
        },
    )


@handles("visit_location_retried", VisitLocationRetriedPayload)
async def visit_location_retried(ctx: EventContext, p: VisitLocationRetriedPayload) -> None:
    visit = await _own_visit(ctx)
    prefix, touched_at = (
        ("arrival", visit.arrived_at) if p.moment == "arrival" else ("finish", visit.finished_at)
    )
    if touched_at is None:  # ese toque aún no existe
        raise Rejected("visit_not_editable")
    previous_state = getattr(visit, f"{prefix}_geo_state")
    if previous_state not in geofence.RETRYABLE_STATES:
        raise Rejected("location_not_retryable")
    if ctx.occurred_at - touched_at > RETRY_WINDOW:
        raise Rejected("retry_window_expired")
    state, distance_m = await _classify_for_visit(ctx.session, visit, p.location)
    _write_geo(visit, prefix, p.location, state, distance_m)
    visit.updated_at = ctx.now
    visit.change_seq = await next_change_seq(ctx.session)
    await _emit_visit_event(
        ctx,
        visit,
        "visit_location_retried",
        {
            "moment": p.moment,
            "previous_geo_state": previous_state,
            **_geo_payload(p.location, state, distance_m),
            "permission": p.permission,
            "duration_ms": p.duration_ms,
        },
    )
