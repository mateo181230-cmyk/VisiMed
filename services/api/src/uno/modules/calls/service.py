"""Orquestador de llamadas: cuándo llamar, a quién, con qué visitas y qué hacer con el resultado.

Ciclo (``run_call_cycle``, cada pocos segundos, seguro con varios trabajadores a la vez):

1. ``expire_reports``: invalida únicamente el resumen 30 minutos después del primer aviso.
2. ``plan_reminders_and_checkins``: llamada previa y chequeo tras 30 minutos reunido.
3. ``plan_calls``: una llamada por visita ``finished`` por defecto; lotes configurables hasta 5.
3. ``place_due_calls``: marca las llamadas que ya tocan y guarda el id de la conversación.
4. ``poll_calls``: consulta el resultado de las llamadas en curso (respaldo del webhook).
5. ``handle_result``: convierte la conversación en fichas por visita, o programa el reintento.

Reglas (doc 01 §12; PRD Tabla 1):

- Solo entre ``call_window_start_hour`` y ``call_window_end_hour`` (hora local del visitador).
- Si el visitador está en otra visita (llegó hace menos de ``call_busy_visit_hours``), se espera.
- Tras un «Terminé» se esperan ``call_batch_wait_seconds`` por si sigue «Otro médico aquí».
- No contesta / ocupado / buzón: reintentos a los +5 y +15 min dentro del plazo original.
- Si elige escribir o no tiene tiempo, queda pendiente en la app y se detienen los reintentos.
- Una reunión que continúa sigue abierta y espera a «Terminé» para solicitar el resumen.
- Una visita solo puede estar en una llamada viva a la vez (índice único parcial).
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock, events
from uno.context import AppContext
from uno.db import next_change_seq
from uno.ids import uuid7
from uno.modules.agenda.models import Visit, VisitLine
from uno.modules.auth.models import User
from uno.modules.calls.context import VisitBrief, build_dynamic_variables
from uno.modules.calls.deadlines import invalidate_report, notify_report, report_expired
from uno.modules.calls.models import Call, CallVisit, VisitReport
from uno.modules.calls.products import refresh_discussed_lines
from uno.modules.calls.provider import (
    ConversationResult,
    DialRequest,
    ProviderError,
)
from uno.modules.calls.schema import (
    MAX_VISITS_PER_CALL,
    callback_minutes,
    interview_complete,
    meeting_finished,
    missing_report_fields,
    parse_analysis,
    report_mode,
)
from uno.modules.catalog.models import Doctor, Institution, ProductLine
from uno.modules.notifications.models import NotificationPreference

log = logging.getLogger("uno.calls")

MAX_CALLS_PER_VISIT = 3  # la llamada inicial y hasta dos de cierre
MAX_ATTEMPTS_HARD = 6  # tope absoluto de marcaciones de una misma llamada
DIAL_LOST_AFTER = timedelta(minutes=2)  # marcada, pero nunca supimos si el proveedor la recibió
FIRST_POLL_AFTER = timedelta(seconds=15)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _set_visit(session: AsyncSession, visit: Visit, status: str, now: datetime) -> None:
    visit.status = status
    visit.updated_at = now
    visit.change_seq = await next_change_seq(session)


def _entities(visit: Visit) -> dict[str, Any]:
    return {
        "visit_id": visit.id,
        "doctor_id": visit.doctor_id,
        "institution_id": visit.institution_id,
        "representative_id": visit.representative_id,
        "product_line_ids": [visit.primary_line_id],
    }


async def _call_visits(session: AsyncSession, call_id: uuid.UUID) -> list[tuple[CallVisit, Visit]]:
    rows = (
        await session.execute(
            select(CallVisit, Visit)
            .join(Visit, Visit.id == CallVisit.visit_id)
            .where(CallVisit.call_id == call_id)
            .order_by(CallVisit.position)
        )
    ).all()
    return [(cv, v) for cv, v in rows]


# ------------------------------------------------------------------------ ciclo


async def run_call_cycle(ctx: AppContext, now: datetime | None = None) -> dict[str, int]:
    """Un paso completo del orquestador. Devuelve cuánto hizo, para los registros."""
    now = now or clock.now()
    stats: Counter[str] = Counter()
    stats.update(await expire_reports(ctx, now))
    if ctx.settings.call_backend == "off" or ctx.voice_provider is None:
        return {k: v for k, v in stats.items() if v}
    for step in (plan_reminders_and_checkins, plan_calls, place_due_calls, poll_calls):
        try:
            stats.update(await step(ctx, now))
        except Exception:
            log.exception("error en el paso %s del ciclo de llamadas", step.__name__)
            stats[f"error_{step.__name__}"] += 1
    return {k: v for k, v in stats.items() if v}


# ------------------------------------------------------------------------ 1. caducar


async def expire_reports(ctx: AppContext, now: datetime) -> dict[str, int]:
    expired = 0
    async with ctx.sessionmaker() as session:
        visits = (
            await session.scalars(
                select(Visit).where(
                    Visit.report_due_at <= now,
                    Visit.report_invalid_at.is_(None),
                )
            )
        ).all()
        for visit in visits:
            report = await session.get(VisitReport, visit.id)
            if report is not None and report.status == "confirmed":
                continue
            await invalidate_report(session, visit, now)
            for _cv, call in (
                await session.execute(
                    select(CallVisit, Call)
                    .join(Call, Call.id == CallVisit.call_id)
                    .where(
                        CallVisit.visit_id == visit.id,
                        CallVisit.live.is_(True),
                        Call.status == "queued",
                    )
                )
            ).all():
                call.status = "cancelled"
                call.updated_at = now
                for link, _ in await _call_visits(session, call.id):
                    link.live = False
            await events.emit(
                session,
                event_type="report_expired",
                occurred_at=now,
                recorded_at=now,
                actor_type="system",
                actor_id=None,
                entities=_entities(visit),
                payload={"window_minutes": 30},
                correlation_id=visit.id,
                source="worker",
            )
            expired += 1
        await session.commit()
    return {"reports_expired": expired}


async def plan_reminders_and_checkins(ctx: AppContext, now: datetime) -> dict[str, int]:
    """Una llamada antes de la cita y un chequeo tras 30 min desde «Llegué»."""
    created: Counter[str] = Counter()
    async with ctx.sessionmaker() as session:
        rows = (
            await session.execute(
                select(Visit, User, NotificationPreference)
                .join(User, User.id == Visit.representative_id)
                .outerjoin(NotificationPreference, NotificationPreference.user_id == User.id)
                .where(Visit.status.in_(("scheduled", "in_progress")), User.is_active)
                .order_by(Visit.scheduled_at)
            )
        ).all()
        for visit, rep, prefs in rows:
            minutes = prefs.call_remind_before_min if prefs else 5
            purpose = "reminder" if visit.status == "scheduled" else "visit_checkin"
            if purpose == "reminder":
                if not minutes or not (
                    visit.scheduled_at - timedelta(minutes=minutes) <= now < visit.scheduled_at
                ):
                    continue
                key = f"{visit.id}:{visit.scheduled_at.isoformat()}"
                prior = await session.scalar(select(Call.id).where(Call.reminder_key == key))
            else:
                if not visit.arrived_at or now < visit.arrived_at + timedelta(minutes=30):
                    continue
                key = None
                prior = await session.scalar(
                    select(Call.id)
                    .join(CallVisit)
                    .where(
                        CallVisit.visit_id == visit.id,
                        Call.purpose == "visit_checkin",
                        Call.status != "cancelled",
                    )
                )
            if prior is not None:
                continue
            live = await session.scalar(
                select(Call.id).where(
                    Call.representative_id == rep.id,
                    Call.status.in_(("queued", "dialing")),
                )
            )
            if live is not None:
                continue
            call = Call(
                id=uuid7(),
                representative_id=rep.id,
                purpose=purpose,
                reminder_key=key,
                scheduled_for=now,
                provider=ctx.voice_provider.name,
                created_at=now,
                updated_at=now,
            )
            session.add(call)
            try:
                await session.flush()
                session.add(CallVisit(call_id=call.id, visit_id=visit.id, position=1))
                await session.commit()
                created[f"{purpose}_calls_planned"] += 1
            except IntegrityError:
                await session.rollback()
    return dict(created)


# ------------------------------------------------------------------------ 2. planear


def _closing_start(now: datetime, tz_name: str, hour: int) -> datetime:
    zone = clock.tz(tz_name)
    local_day: date = now.astimezone(zone).date()
    return datetime.combine(local_day, time(hour), tzinfo=zone).astimezone(UTC)


async def plan_calls(ctx: AppContext, now: datetime) -> dict[str, int]:
    s = ctx.settings
    assert ctx.voice_provider is not None
    created = 0
    async with ctx.sessionmaker() as session:
        finished = (
            (
                await session.execute(
                    select(Visit).where(
                        Visit.status == "finished",
                        Visit.report_invalid_at.is_(None),
                        (Visit.report_mode.is_(None) | (Visit.report_mode == "voice")),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not finished:
            return {}
        ids = [v.id for v in finished]

        live_ids = set(
            (
                await session.execute(
                    select(CallVisit.visit_id).where(
                        CallVisit.visit_id.in_(ids), CallVisit.live.is_(True)
                    )
                )
            ).scalars()
        )
        history: dict[uuid.UUID, tuple[int, datetime | None]] = {
            visit_id: (count, _utc(last))
            for visit_id, count, last in (
                await session.execute(
                    select(CallVisit.visit_id, func.count(), func.max(Call.created_at))
                    .join(Call, Call.id == CallVisit.call_id)
                    .where(
                        CallVisit.visit_id.in_(ids),
                        Call.status != "cancelled",
                        Call.purpose == "summary",
                    )
                    .group_by(CallVisit.visit_id)
                )
            ).all()
        }
        reps_with_live_call = set(
            (
                await session.execute(
                    select(Call.representative_id).where(
                        Call.status.in_(("queued", "dialing")), Call.direction == "outbound"
                    )
                )
            ).scalars()
        )
        busy_reps = set(
            (
                await session.execute(
                    select(Visit.representative_id).where(
                        Visit.status == "in_progress",
                        Visit.arrived_at > now - timedelta(hours=s.call_busy_visit_hours),
                    )
                )
            ).scalars()
        )
        rep_ids = {v.representative_id for v in finished}
        users = {
            u.id: u
            for u in (
                await session.execute(select(User).where(User.id.in_(rep_ids), User.is_active))
            ).scalars()
        }

        by_rep: dict[uuid.UUID, list[Visit]] = defaultdict(list)
        for visit in finished:
            if visit.id not in live_ids:
                by_rep[visit.representative_id].append(visit)

        for rep_id, visits in by_rep.items():
            user = users.get(rep_id)
            if user is None or rep_id in busy_reps or rep_id in reps_with_live_call:
                continue
            if (
                s.call_backend == "elevenlabs"
                and s.env != "prod"
                and s.dial_phone(user.phone_e164) not in s.allowed_call_phones
            ):
                continue  # en pruebas solo se llama a celulares autorizados
            local_now = now.astimezone(clock.tz(user.timezone))
            if not s.call_window_start_hour <= local_now.hour < s.call_window_end_hour:
                continue

            closing_start = _closing_start(now, user.timezone, s.call_closing_hour)
            eligible: list[Visit] = []
            for visit in visits:
                count, last_created = history.get(visit.id, (0, None))
                if count == 0:
                    eligible.append(visit)
                elif (
                    count < MAX_CALLS_PER_VISIT
                    and now >= closing_start
                    and (last_created is None or last_created < closing_start)
                ):
                    eligible.append(visit)  # llamada de cierre: solo una por día y visita
            if not eligible:
                continue

            last_touch = max(_utc(v.updated_at) or now for v in eligible)
            if now - last_touch < timedelta(seconds=s.call_batch_wait_seconds):
                continue  # puede venir «Otro médico aquí»

            eligible.sort(key=lambda v: _utc(v.finished_at) or _utc(v.updated_at) or now)
            batch = eligible[: min(s.call_max_visits_per_call, MAX_VISITS_PER_CALL)]
            is_closing = any(history.get(v.id, (0, None))[0] > 0 for v in batch)
            call = Call(
                id=uuid7(),
                representative_id=rep_id,
                direction="outbound",
                status="queued",
                scheduled_for=now,
                is_closing=is_closing,
                provider=ctx.voice_provider.name,
                created_at=now,
                updated_at=now,
            )
            session.add(call)
            await session.flush()
            for position, visit in enumerate(batch, start=1):
                session.add(CallVisit(call_id=call.id, visit_id=visit.id, position=position))
            try:
                await session.commit()
                created += 1
            except IntegrityError:  # otro trabajador ya tomó alguna de estas visitas
                await session.rollback()
    return {"calls_planned": created}


# ------------------------------------------------------------------------ 3. marcar


async def place_due_calls(ctx: AppContext, now: datetime) -> dict[str, int]:
    async with ctx.sessionmaker() as session:
        due = list(
            (
                await session.execute(
                    select(Call.id)
                    .where(Call.status == "queued", Call.scheduled_for <= now)
                    .order_by(Call.scheduled_for)
                    .limit(10)
                )
            ).scalars()
        )
    placed = 0
    for call_id in due:
        if await _dial(ctx, call_id, now):
            placed += 1
    return {"calls_placed": placed}


async def _briefs(session: AsyncSession, call_id: uuid.UUID) -> list[VisitBrief]:
    rows = (
        await session.execute(
            select(Visit, Doctor, Institution, ProductLine)
            .join(CallVisit, CallVisit.visit_id == Visit.id)
            .join(Doctor, Doctor.id == Visit.doctor_id)
            .outerjoin(Institution, Institution.id == Visit.institution_id)
            .join(ProductLine, ProductLine.id == Visit.primary_line_id)
            .where(CallVisit.call_id == call_id)
            .order_by(CallVisit.position)
        )
    ).all()
    briefs = []
    for visit, doctor, institution, line in rows:
        previous_action, previous_at = await previous_followup(session, visit)
        briefs.append(
            VisitBrief(
                doctor_name=doctor.full_name,
                institution=institution.name if institution else None,
                line_code=line.code,
                scheduled_at=_utc(visit.scheduled_at) or clock.now(),
                arrived_at=_utc(visit.arrived_at),
                previous_next_action=previous_action,
                previous_visit_at=previous_at,
                report_due_at=visit.report_due_at,
            )
        )
    return briefs


async def previous_followup(
    session: AsyncSession,
    visit: Visit,
) -> tuple[str | None, datetime | None]:
    """Pendiente confirmado del mismo visitador, médico y línea realmente presentada."""
    rows = (
        await session.execute(
            select(Visit, VisitReport)
            .join(VisitReport, VisitReport.visit_id == Visit.id)
            .join(VisitLine, VisitLine.visit_id == Visit.id)
            .where(
                Visit.representative_id == visit.representative_id,
                Visit.doctor_id == visit.doctor_id,
                Visit.id != visit.id,
                Visit.scheduled_at < visit.scheduled_at,
                Visit.status == "confirmed",
                VisitReport.status == "confirmed",
                VisitLine.role == "discussed",
                VisitLine.line_id == visit.primary_line_id,
            )
            .order_by(Visit.scheduled_at.desc())
            .limit(10)
        )
    ).all()
    for previous, report in rows:
        if missing_report_fields(report.fields or {}):
            continue
        field = (report.fields or {}).get("next_action") or {}
        action = field.get("value")
        if isinstance(action, str) and action.strip() and field.get("confidence") != "low":
            return action.strip()[:500], _utc(previous.finished_at or previous.scheduled_at)
    return None, None


async def _dial(ctx: AppContext, call_id: uuid.UUID, now: datetime) -> bool:
    s = ctx.settings
    provider = ctx.voice_provider
    assert provider is not None
    async with ctx.sessionmaker() as session:
        call = await session.get(Call, call_id)
        if call is None or call.status != "queued" or _utc(call.scheduled_for) > now:  # type: ignore[operator]
            return False
        rep = await session.get(User, call.representative_id)
        if rep is None or not rep.is_active:
            call.status = "cancelled"
            call.updated_at = now
            for cv, _ in await _call_visits(session, call_id):
                cv.live = False
            await session.commit()
            return False
        local_hour = now.astimezone(clock.tz(rep.timezone)).hour
        pairs = await _call_visits(session, call_id)
        obsolete = False
        for _, visit in pairs:
            if call.purpose == "reminder":
                prefs = await session.get(NotificationPreference, rep.id)
                minutes = prefs.call_remind_before_min if prefs else 5
                obsolete |= (
                    visit.status != "scheduled"
                    or not minutes
                    or now >= visit.scheduled_at
                    or call.reminder_key != f"{visit.id}:{visit.scheduled_at.isoformat()}"
                )
                if (
                    not obsolete
                    and minutes
                    and now < visit.scheduled_at - timedelta(minutes=minutes)
                ):
                    return False
            else:
                report = await session.get(VisitReport, visit.id)
                obsolete |= (
                    report_expired(visit, now)
                    or (report is not None and report.status == "confirmed")
                    or visit.report_mode in ("written", "deferred")
                    or (call.purpose == "visit_checkin" and visit.status != "in_progress")
                )
        if obsolete:
            call.status = "cancelled"
            call.updated_at = now
            for cv, _ in pairs:
                cv.live = False
            await session.commit()
            return False
        if not s.call_window_start_hour <= local_hour < s.call_window_end_hour:
            return False  # fuera de horario: sigue en cola hasta mañana
        busy = await session.scalar(
            select(Visit.id)
            .where(
                Visit.representative_id == rep.id,
                Visit.status == "in_progress",
                Visit.arrived_at > now - timedelta(hours=s.call_busy_visit_hours),
                Visit.id.not_in(
                    [v.id for _, v in pairs] if call.purpose == "visit_checkin" else []
                ),
            )
            .limit(1)
        )
        if busy is not None:
            return False  # pudo entrar a otra visita mientras la llamada esperaba el reintento
        if (
            s.call_backend == "elevenlabs"
            and s.env != "prod"
            and s.dial_phone(rep.phone_e164) not in s.allowed_call_phones
        ):
            await _fail_now(session, ctx, call, "phone_not_allowed", now)
            await session.commit()
            return False

        claimed = await session.execute(
            update(Call)
            .where(Call.id == call_id, Call.status == "queued")
            .values(status="dialing", attempt=Call.attempt + 1, dialed_at=now, updated_at=now)
        )
        await session.commit()
        if claimed.rowcount != 1:  # type: ignore[attr-defined]
            return False  # otro trabajador la tomó
        briefs = await _briefs(session, call_id)
        variables = build_dynamic_variables(
            rep.full_name,
            briefs,
            tz_name=rep.timezone,
            include_names=s.call_include_doctor_names,
            now=now,
            purpose=call.purpose,
        )
        if call.purpose != "reminder":
            for index, (_, visit) in enumerate(pairs, 1):
                due = visit.report_due_at or (now + timedelta(minutes=30))
                from uno.modules.calls.context import spoken_time

                variables["visitas_texto"] += (
                    f"\nResumen {index}: vence a {spoken_time(due, rep.timezone)}."
                )
        variables["call_id"] = str(call_id)
        phone = s.dial_phone(rep.phone_e164)

    try:
        dialed = await provider.place_call(DialRequest(call_id, phone, variables))
    except ProviderError as exc:
        log.warning("no se pudo marcar la llamada %s: %s", call_id, exc)
        async with ctx.sessionmaker() as session:
            await _attempt_failed(
                session, ctx, call_id, "provider_error", now, retryable=exc.retryable
            )
            await session.commit()
        return False

    async with ctx.sessionmaker() as session:
        call = await session.get(Call, call_id)
        assert call is not None
        call.provider_conversation_id = dialed.conversation_id
        call.provider_call_id = dialed.provider_call_id
        call.updated_at = now
        pairs = await _call_visits(session, call_id)
        for _, visit in pairs:
            if call.purpose != "reminder":
                await notify_report(session, visit, now)
            if call.purpose == "summary" and visit.status == "finished":
                await _set_visit(session, visit, "in_call", now)
        await events.emit(
            session,
            event_type="call_placed",
            occurred_at=now,
            recorded_at=now,
            actor_type="system",
            actor_id=None,
            entities={
                "call_id": call_id,
                "representative_id": call.representative_id,
                "visit_ids": [v.id for _, v in pairs],
            },
            payload={"attempt": call.attempt, "is_closing": call.is_closing, "visits": len(pairs)},
            correlation_id=call_id,
            source="worker",
        )
        await session.commit()
    return True


# ------------------------------------------------------------------------ fallas y reintentos


async def _fail_now(
    session: AsyncSession, ctx: AppContext, call: Call, reason: str, now: datetime
) -> None:
    """Falla definitiva: sin reintentos."""
    call.status = "failed"
    call.failure_reason = reason
    call.ended_at = now
    call.updated_at = now
    for cv, visit in await _call_visits(session, call.id):
        cv.live = False
        if visit.status == "in_call":
            await _set_visit(session, visit, "finished", now)
    await events.emit(
        session,
        event_type="call_failed",
        occurred_at=now,
        recorded_at=now,
        actor_type="system",
        actor_id=None,
        entities={"call_id": call.id, "representative_id": call.representative_id},
        payload={"reason": reason, "attempt": call.attempt},
        correlation_id=call.id,
        source="worker",
    )


async def _attempt_failed(
    session: AsyncSession,
    ctx: AppContext,
    call_id: uuid.UUID,
    reason: str,
    now: datetime,
    *,
    retryable: bool = True,
    retry_at: datetime | None = None,
) -> str:
    """Una marcación fallida: reprograma (+5, +15 min o lo que pida el visitador) o la falla."""
    call = (
        await session.execute(select(Call).where(Call.id == call_id).with_for_update())
    ).scalar_one_or_none()
    if call is None or call.status != "dialing":
        return "stale"
    if call.purpose == "reminder":
        retryable = False
    delays = ctx.settings.call_retry_delays
    if retry_at is None and retryable and call.attempt <= len(delays):
        retry_at = now + delays[call.attempt - 1]
    pairs = await _call_visits(session, call.id)
    deadlines = [v.report_due_at for _, v in pairs if v.report_due_at]
    if retry_at is not None and deadlines and retry_at >= min(deadlines):
        retryable = False
    if retry_at is None or not retryable or call.attempt >= MAX_ATTEMPTS_HARD:
        await _fail_now(session, ctx, call, reason, now)
        return "failed"

    call.status = "queued"
    call.scheduled_for = retry_at
    call.failure_reason = reason
    call.provider_conversation_id = None
    call.provider_call_id = None
    call.updated_at = now
    for _, visit in await _call_visits(session, call.id):
        if visit.status == "in_call":
            await _set_visit(session, visit, "finished", now)
    await events.emit(
        session,
        event_type="call_retry_scheduled",
        occurred_at=now,
        recorded_at=now,
        actor_type="system",
        actor_id=None,
        entities={"call_id": call.id, "representative_id": call.representative_id},
        payload={
            "reason": reason,
            "attempt": call.attempt,
            "retry_in_s": int((retry_at - now).total_seconds()),
        },
        correlation_id=call.id,
        source="worker",
    )
    return "retry"


# ------------------------------------------------------------------------ 4. consultar


async def poll_calls(ctx: AppContext, now: datetime) -> dict[str, int]:
    provider = ctx.voice_provider
    assert provider is not None
    timeout = timedelta(minutes=ctx.settings.call_result_timeout_minutes)
    async with ctx.sessionmaker() as session:
        dialing = (
            (await session.execute(select(Call).where(Call.status == "dialing"))).scalars().all()
        )
    stats: Counter[str] = Counter()
    for call in dialing:
        dialed_at = _utc(call.dialed_at) or now
        age = now - dialed_at
        if not call.provider_conversation_id:
            if age > DIAL_LOST_AFTER:
                async with ctx.sessionmaker() as session:
                    outcome = await _attempt_failed(session, ctx, call.id, "dial_lost", now)
                    await session.commit()
                stats[f"calls_{outcome}"] += 1
            continue
        if age < FIRST_POLL_AFTER:
            continue
        try:
            result = await provider.fetch_conversation(call.provider_conversation_id)
        except ProviderError as exc:
            log.warning("no se pudo consultar la llamada %s: %s", call.id, exc)
            result = None
        if result is None or result.status == "pending":
            if age > timeout:
                async with ctx.sessionmaker() as session:
                    outcome = await _attempt_failed(session, ctx, call.id, "timeout", now)
                    await session.commit()
                stats[f"calls_{outcome}"] += 1
            continue
        stats[f"calls_{await handle_result(ctx, call.id, result, now)}"] += 1
    return dict(stats)


# ------------------------------------------------------------------------ 5. resultado


def _field_json(parsed_fields: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        name: {"value": fv.value, "confidence": fv.confidence, "source": fv.source}
        for name, fv in parsed_fields.items()
    }


async def _upsert_report(
    session: AsyncSession,
    visit: Visit,
    call: Call,
    fields: dict[str, dict[str, Any]],
    *,
    complete: bool,
    problems: list[str],
    now: datetime,
) -> VisitReport | None:
    existing = await session.get(VisitReport, visit.id)
    if existing is not None and existing.status == "confirmed":
        return None  # una ficha confirmada no se vuelve a tocar
    if existing is not None:
        # Lo que corrigió el visitador nunca lo pisa la llamada (PRD, Tabla 3: conflictos).
        for name, entry in (existing.fields or {}).items():
            if entry.get("source") == "rep_edit":
                fields[name] = entry
    change_seq = await next_change_seq(session)
    if existing is None:
        report = VisitReport(
            visit_id=visit.id,
            call_id=call.id,
            status="ready",
            fields=fields,
            complete=not missing_report_fields(fields),
            problems=problems,
            created_at=now,
            updated_at=now,
            change_seq=change_seq,
            extractor_version="elevenlabs-v2",
        )
        session.add(report)
        return report
    existing.call_id = call.id
    existing.fields = fields
    existing.complete = not missing_report_fields(fields)
    existing.extractor_version = "elevenlabs-v2"
    existing.problems = problems
    existing.updated_at = now
    existing.change_seq = change_seq
    return existing


async def handle_result(
    ctx: AppContext, call_id: uuid.UUID, result: ConversationResult, now: datetime
) -> str:
    """Aplica el resultado de una conversación a su llamada. Idempotente.

    Devuelve ``completed`` | ``retry`` | ``failed`` | ``pending`` | ``stale``.
    """
    if result.status == "pending":
        return "pending"
    async with ctx.sessionmaker() as session:
        call = (
            await session.execute(select(Call).where(Call.id == call_id).with_for_update())
        ).scalar_one_or_none()
        if (
            call is None
            or call.status != "dialing"
            or (
                call.provider_conversation_id
                and result.conversation_id
                and call.provider_conversation_id != result.conversation_id
            )
        ):
            return "stale"  # repetido, tardío o de un intento anterior

        connected = result.status == "done" and result.user_turns > 0 and not result.voicemail
        if not connected:
            reason = (
                result.failure_reason
                or ("voicemail" if result.voicemail else None)
                or ("no_answer" if result.status == "done" else result.termination_reason)
                or "provider_failed"
            )
            outcome = await _attempt_failed(session, ctx, call_id, reason, now)
            await session.commit()
            return outcome

        pairs = await _call_visits(session, call_id)
        mode = report_mode(result.data_collection)
        ongoing = call.purpose == "visit_checkin" and not meeting_finished(result.data_collection)
        if call.purpose == "reminder" or mode in ("written", "deferred") or ongoing:
            call.status = "completed"
            call.transcript = result.transcript_json()
            call.analysis = result.data_collection
            call.duration_s = result.duration_s
            call.ended_at = now
            call.updated_at = now
            for cv, visit in pairs:
                cv.live = False
                if call.purpose == "reminder":
                    continue
                if ongoing:
                    visit.report_notified_at = None
                    visit.report_due_at = None
                    visit.report_invalid_at = None
                    visit.report_mode = None
                else:
                    visit.report_mode = mode
                    if call.purpose == "visit_checkin" and meeting_finished(result.data_collection):
                        visit.finished_at = visit.finished_at or now
                        visit.finish_geo_state = visit.finish_geo_state or "sin_gps"
                        visit.status = "finished"
                    if visit.status == "in_call":
                        visit.status = "finished"
                    if report_expired(visit, now):
                        await invalidate_report(session, visit, now)
                visit.updated_at = now
                visit.change_seq = await next_change_seq(session)
            await session.commit()
            return "completed"
        if call.purpose == "visit_checkin" and not meeting_finished(result.data_collection):
            # No convertir un sí ambiguo o extracción comercial en cierre de reunión.
            outcome = await _attempt_failed(session, ctx, call.id, "incomplete", now)
            await session.commit()
            return outcome
        if call.purpose == "visit_checkin":
            for _, visit in pairs:
                if visit.status == "in_progress":
                    visit.finished_at = now
                    visit.finish_geo_state = "sin_gps"
                    await _set_visit(session, visit, "finished", now)
        parsed = parse_analysis(result.data_collection, len(pairs))
        if not any(p.fields for p in parsed):
            # Contestó pero no contó nada (por ejemplo, «ahorita no puedo»).
            minutes = callback_minutes(result.data_collection)
            outcome = await _attempt_failed(
                session,
                ctx,
                call_id,
                "incomplete",
                now,
                retry_at=now + timedelta(minutes=minutes) if minutes else None,
            )
            await session.commit()
            return outcome

        call.transcript = result.transcript_json()
        call.analysis = result.data_collection
        call.summary = (result.summary or "")[:2000] or None
        call.duration_s = result.duration_s
        call.ended_at = now
        call.status = "completed"
        call.failure_reason = None
        call.updated_at = now

        rep = await session.get(User, call.representative_id)
        tz_name = rep.timezone if rep else ctx.settings.default_timezone
        today = clock.local_date(_utc(call.dialed_at) or now, tz_name)
        voice_confirmed = result.has_confirmed_readbacks(len(pairs))
        offset = result.confirmed_readback_offset(len(pairs))
        confirmed_at = (
            min(now, (_utc(call.dialed_at) or now) + timedelta(seconds=offset))
            if offset is not None
            else now
        )
        reports = 0
        for (cv, visit), pv in zip(pairs, parsed, strict=False):
            cv.live = False
            if not pv.fields:
                if visit.status == "in_call":
                    await _set_visit(session, visit, "finished", now)
                continue
            fields = _field_json(pv.fields)
            days = fields.get("next_action_in_days")
            concrete_date = fields.get("next_action_date")
            if concrete_date:
                fields["next_action_due"] = dict(concrete_date)
            elif days:
                fields["next_action_due"] = {
                    "value": (today + timedelta(days=int(days["value"]))).isoformat(),
                    "confidence": days["confidence"],
                    "source": "call",
                }
            report = await _upsert_report(
                session, visit, call, fields, complete=pv.complete, problems=pv.problems, now=now
            )
            if report is None:
                continue
            await refresh_discussed_lines(session, visit.id, report.fields)
            reports += 1
            confirmed_in_time = (
                pv.confirmed
                and voice_confirmed
                and visit.report_mode != "written"
                and (visit.report_due_at is None or confirmed_at < visit.report_due_at)
            )
            if report_expired(visit, now) and not confirmed_in_time:
                await invalidate_report(session, visit, now)
            if confirmed_in_time:
                visit.report_invalid_at = None
                report.status = "confirmed"
                report.confirmed_at = confirmed_at
                await _set_visit(session, visit, "confirmed", now)
                await events.emit(
                    session,
                    event_type="report_confirmed",
                    occurred_at=confirmed_at,
                    recorded_at=now,
                    actor_type="representative",
                    actor_id=call.representative_id,
                    entities=_entities(visit),
                    payload={"via": "voice", "call_id": call.id, "complete": report.complete},
                    correlation_id=visit.id,
                    causation_id=call.id,
                    source="worker",
                )
            if visit.status in ("in_call", "finished", "processing"):
                await _set_visit(session, visit, "ready", now)
            await events.emit(
                session,
                event_type="visit_extracted",
                occurred_at=now,
                recorded_at=now,
                actor_type="system",
                actor_id=None,
                entities=_entities(visit),
                payload={
                    "call_id": call.id,
                    "extractor": "elevenlabs-v2",
                    "complete": report.complete,
                    "fields_extracted": len(pv.fields),
                    "low_confidence_fields": sum(
                        1 for f in pv.fields.values() if f.confidence == "low"
                    ),
                    **{
                        key: fields[key]["value"]
                        for key in (
                            "interest_level",
                            "receptiveness_score",
                            "visit_outcome",
                            "order_taken",
                            "no_order_reason",
                            "receptiveness",
                            "samples_delivered",
                            "next_action_in_days",
                        )
                        if key in fields
                    },
                },
                correlation_id=visit.id,
                causation_id=call.id,
                source="worker",
            )
        await events.emit(
            session,
            event_type="call_completed",
            occurred_at=now,
            recorded_at=now,
            actor_type="system",
            actor_id=None,
            entities={
                "call_id": call.id,
                "representative_id": call.representative_id,
                "visit_ids": [v.id for _, v in pairs],
            },
            payload={
                "attempt": call.attempt,
                "duration_s": call.duration_s,
                "visits": len(pairs),
                "reports": reports,
                "interview_complete": interview_complete(result.data_collection),
            },
            correlation_id=call.id,
            source="worker",
        )
        await session.commit()
        return "completed"


# ------------------------------------------------------------------------ webhook


async def handle_failure_event(
    ctx: AppContext, conversation_id: str, user_id: str | None, reason: str, now: datetime
) -> str:
    """``call_initiation_failure``: no contestó, ocupado o falla desconocida."""
    call_id = await find_call(ctx, conversation_id, user_id)
    if call_id is None:
        return "unknown"
    result = ConversationResult(conversation_id, "failed", failure_reason=reason)
    return await handle_result(ctx, call_id, result, now)


async def find_call(
    ctx: AppContext, conversation_id: str | None, user_id: str | None
) -> uuid.UUID | None:
    """Llave doble: id de la conversación y, si no aparece, el ``user_id`` (= id de la llamada)."""
    async with ctx.sessionmaker() as session:
        if conversation_id:
            found = (
                await session.execute(
                    select(Call.id).where(Call.provider_conversation_id == conversation_id)
                )
            ).scalar_one_or_none()
            if found is not None:
                return found
        if user_id:
            try:
                candidate = uuid.UUID(str(user_id))
            except ValueError:
                return None
            return (
                await session.execute(select(Call.id).where(Call.id == candidate))
            ).scalar_one_or_none()
    return None
