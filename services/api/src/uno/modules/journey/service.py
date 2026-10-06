"""Visit-scoped preparation. Time is reported active time, never proof of attention."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock, events
from uno.context import AppContext
from uno.db import next_change_seq
from uno.errors import ApiError, not_found
from uno.modules.agenda.models import Visit, VisitLine
from uno.modules.auth.models import User
from uno.modules.calls.models import Call, CallVisit, VisitReport
from uno.modules.catalog.models import Doctor
from uno.modules.journey.chat_budget import (
    QUESTION_TIMEOUT_SECONDS,
    check_chat_budget,
    lock_chat_user,
)
from uno.modules.journey.feedback import RUBRIC_VERSION, feedback_for, text_evidence
from uno.modules.journey.models import PreparationActivity, PreparationMessage, VisitPreparation
from uno.modules.journey.schema import (
    ActivityPayload,
    AIAvailabilityOut,
    ContextOut,
    ManagerMetricsOut,
    ManagerVisitOut,
    MessageOut,
    PreparationMetricsOut,
    PreparationOut,
    PreparationPatch,
    QuestionIn,
    TranscriptOut,
    TranscriptTurnOut,
)

MAX_PREPARATION_AGE = timedelta(days=732)
FUTURE_GRACE = timedelta(minutes=5)


async def own_visit(session: AsyncSession, user: User, visit_id: uuid.UUID) -> Visit:
    visit = await session.get(Visit, visit_id)
    if visit is None or visit.representative_id != user.id:
        raise not_found("No encontramos esta visita")
    return visit


def check_preparation_time(visit: Visit, occurred_at: datetime, now: datetime) -> None:
    if occurred_at > now + FUTURE_GRACE or occurred_at < now - MAX_PREPARATION_AGE:
        raise ApiError(422, "invalid_preparation_time", "Revisa la fecha y hora de tu teléfono")
    preparation_ended_at = visit.arrived_at or visit.finished_at
    if preparation_ended_at and occurred_at > preparation_ended_at:
        raise ApiError(409, "preparation_closed", "La preparación terminó al iniciar la visita")
    if visit.status != "scheduled" and preparation_ended_at is None:
        raise ApiError(409, "preparation_closed", "Esta visita ya no está pendiente de iniciar")
    if visit.status == "not_done":
        raise ApiError(409, "preparation_closed", "Esta visita fue cancelada")


async def locked_preparation(
    session: AsyncSession, visit: Visit, now: datetime
) -> VisitPreparation:
    # UPSERT takes a write lock in SQLite as well as PostgreSQL and handles first-write races.
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(VisitPreparation).values(
        visit_id=visit.id,
        objective=None,
        rep_commitment=None,
        objective_edited=False,
        rep_commitment_edited=False,
        active_seconds=0,
        prepared_at=None,
        prepared_recorded_at=None,
        created_at=now,
        updated_at=now,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[VisitPreparation.visit_id],
            set_={"updated_at": VisitPreparation.updated_at},
        )
    )
    row = await session.get(VisitPreparation, visit.id, populate_existing=True)
    assert row is not None
    return row


async def touch(
    session: AsyncSession, visit: Visit, preparation: VisitPreparation, now: datetime
) -> None:
    preparation.updated_at = now
    visit.updated_at = now
    visit.change_seq = await next_change_seq(session)


async def previous_report(session: AsyncSession, visit: Visit) -> tuple[Visit, VisitReport] | None:
    discussed = (
        select(VisitLine.visit_id)
        .where(VisitLine.visit_id == Visit.id, VisitLine.role == "discussed")
        .exists()
    )
    matching = (
        select(VisitLine.visit_id)
        .where(
            VisitLine.visit_id == Visit.id,
            VisitLine.role == "discussed",
            VisitLine.line_id == visit.primary_line_id,
        )
        .exists()
    )
    row = (
        await session.execute(
            select(Visit, VisitReport)
            .join(VisitReport, VisitReport.visit_id == Visit.id)
            .where(
                Visit.representative_id == visit.representative_id,
                Visit.doctor_id == visit.doctor_id,
                Visit.id != visit.id,
                Visit.scheduled_at < visit.scheduled_at,
                Visit.status == "confirmed",
                VisitReport.status == "confirmed",
                or_(matching, and_(~discussed, Visit.primary_line_id == visit.primary_line_id)),
            )
            .order_by(Visit.scheduled_at.desc(), VisitReport.updated_at.desc(), Visit.id.desc())
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def preparation_context(session: AsyncSession, visit: Visit) -> dict[str, Any]:
    preparation = await session.get(VisitPreparation, visit.id)
    source = await previous_report(session, visit)
    previous, report = source if source else (None, None)
    objective = text_evidence(report, "next_visit_objective")
    commitment = text_evidence(report, "representative_commitment") or text_evidence(
        report, "next_action"
    )
    if preparation:
        if preparation.objective_edited:
            objective = preparation.objective
        if preparation.rep_commitment_edited:
            commitment = preparation.rep_commitment
    interest = text_evidence(report, "doctor_interest")
    doctor_commitment = text_evidence(report, "doctor_commitment")
    topic = doctor_commitment or interest
    opening = (
        f"La última vez hablamos de lo siguiente: {topic}. ¿Tuvo oportunidad de considerarlo?"
        if topic
        else "¿Qué necesidad le gustaría que revisáramos hoy y qué sería un siguiente paso útil?"
    )
    message = (
        "Retoma lo conversado, escucha qué ocurrió desde la última visita y acuerda un próximo "
        "paso concreto. Evita repetir toda la presentación desde cero."
        if report
        else (
            "Comienza por conocer la necesidad del médico y acuerda un objetivo "
            "para la conversación."
        )
    )
    context = ContextOut(
        source_visit_id=previous.id if previous else None,
        source_at=(previous.finished_at or previous.scheduled_at) if previous else None,
        summary=text_evidence(report, "summary"),
        doctor_interest=interest,
        barrier=text_evidence(report, "objection"),
        current_preference=text_evidence(report, "current_preference"),
        doctor_commitment=doctor_commitment,
        opening_question=opening,
        recommended_message=message,
    )
    sentences = [context.summary or "Aún no hay un resumen confirmado anterior para esta línea."]
    sentences.append(
        f"Tu compromiso pendiente: {commitment}."
        if commitment
        else "No hay un compromiso pendiente registrado; confírmalo con el médico."
    )
    sentences.append(
        f"El objetivo de hoy: {objective}."
        if objective
        else "Define qué quieres lograr hoy antes de empezar la conversación."
    )
    if context.barrier:
        sentences.append(f"Ten presente la barrera registrada: {context.barrier}.")
    return {
        "objective": objective,
        "rep_commitment": commitment,
        "context": context.model_dump(mode="json"),
        "brief": " ".join(sentences),
    }


async def previous_transcript(session: AsyncSession, visit: Visit) -> TranscriptOut:
    source = await previous_report(session, visit)
    if not source or not source[1].call_id:
        return TranscriptOut(status="missing", turns=[])
    previous, report = source
    call = await session.get(Call, report.call_id)
    if not call or call.representative_id != visit.representative_id:
        return TranscriptOut(status="missing", turns=[])
    links = (
        await session.scalars(select(CallVisit.visit_id).where(CallVisit.call_id == call.id))
    ).all()
    # A whole multi-visit call is not a doctor's transcript. Do not leak another visit's text.
    if len(links) > 1:
        return TranscriptOut(status="shared_call", turns=[])
    if list(links) != [previous.id] or not call.transcript:
        return TranscriptOut(status="missing", turns=[])
    turns = [
        TranscriptTurnOut(role=turn["role"], text=str(turn["text"]))
        for turn in call.transcript
        if isinstance(turn, dict)
        and turn.get("role") in ("agent", "user")
        and isinstance(turn.get("text"), str)
    ]
    return TranscriptOut(status="available" if turns else "missing", turns=turns)


async def answered_messages(session: AsyncSession, visit_id: uuid.UUID) -> list[PreparationMessage]:
    return list(
        (
            await session.scalars(
                select(PreparationMessage)
                .where(
                    PreparationMessage.visit_id == visit_id, PreparationMessage.status == "answered"
                )
                .order_by(PreparationMessage.created_at, PreparationMessage.request_id)
            )
        ).all()
    )


def message_out(row: PreparationMessage) -> MessageOut:
    return MessageOut(
        request_id=row.request_id,
        question=row.question,
        answer=row.answer or "",
        created_at=row.created_at,
    )


async def preparation_view(session: AsyncSession, ctx: AppContext, visit: Visit) -> PreparationOut:
    preparation = await session.get(VisitPreparation, visit.id)
    messages = await answered_messages(session, visit.id)
    provider = getattr(ctx, "journey_provider", None)
    return PreparationOut(
        visit_id=visit.id,
        **await preparation_context(session, visit),
        previous_transcript=await previous_transcript(session, visit),
        metrics=PreparationMetricsOut(
            active_seconds=preparation.active_seconds if preparation else 0,
            prepared_at=preparation.prepared_at if preparation else None,
            prepared_recorded_at=preparation.prepared_recorded_at if preparation else None,
            question_count=len(messages),
        ),
        messages=[message_out(row) for row in messages],
        ai=AIAvailabilityOut(
            available=provider is not None, mode=provider.name if provider else "off"
        ),
    )


async def update_preparation(
    session: AsyncSession,
    visit: Visit,
    payload: PreparationPatch,
    *,
    occurred_at: datetime,
    now: datetime,
) -> None:
    check_preparation_time(visit, occurred_at, now)
    preparation = await locked_preparation(session, visit, now)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(preparation, key, value)
        setattr(preparation, f"{key}_edited", True)
    await touch(session, visit, preparation, now)


async def mark_prepared(
    session: AsyncSession, visit: Visit, *, occurred_at: datetime, now: datetime
) -> None:
    check_preparation_time(visit, occurred_at, now)
    preparation = await locked_preparation(session, visit, now)
    # Earliest mark wins, including a day-before mark delivered after reconnecting.
    if preparation.prepared_at is not None and preparation.prepared_at <= occurred_at:
        return
    preparation.prepared_at = min(occurred_at, now)
    preparation.prepared_recorded_at = now
    await touch(session, visit, preparation, now)
    await events.emit(
        session,
        event_type="visit_prepared",
        occurred_at=preparation.prepared_at,
        recorded_at=now,
        actor_type="rep",
        actor_id=visit.representative_id,
        entities={"visit_id": visit.id},
        payload={"active_seconds": preparation.active_seconds},
    )


async def record_activity(
    session: AsyncSession,
    visit: Visit,
    payload: ActivityPayload,
    *,
    event_id: uuid.UUID,
    now: datetime,
) -> None:
    check_preparation_time(visit, payload.ended_at, now)
    preparation = await locked_preparation(session, visit, now)
    existing = await session.get(PreparationActivity, event_id)
    if existing:
        if (
            existing.visit_id,
            existing.started_at,
            existing.ended_at,
            existing.reported_seconds,
        ) != (visit.id, payload.started_at, payload.ended_at, payload.seconds):
            raise ApiError(409, "activity_id_conflict", "Este registro de tiempo ya se utilizó")
        return
    overlaps = (
        await session.scalars(
            select(PreparationActivity)
            .where(
                PreparationActivity.visit_id == visit.id,
                PreparationActivity.started_at < payload.ended_at,
                PreparationActivity.ended_at > payload.started_at,
            )
            .order_by(PreparationActivity.started_at)
        )
    ).all()
    covered = 0.0
    cursor = payload.started_at
    for row in overlaps:
        start = max(cursor, row.started_at)
        end = min(payload.ended_at, row.ended_at)
        if end > start:
            covered += (end - start).total_seconds()
            cursor = end
    available = max(0, int((payload.ended_at - payload.started_at).total_seconds() - covered))
    credited = min(payload.seconds, available)
    session.add(
        PreparationActivity(
            event_id=event_id,
            visit_id=visit.id,
            started_at=payload.started_at,
            ended_at=payload.ended_at,
            reported_seconds=payload.seconds,
            seconds=credited,
            recorded_at=now,
        )
    )
    preparation.active_seconds += credited
    await touch(session, visit, preparation, now)


async def answer_question(
    session: AsyncSession,
    ctx: AppContext,
    user: User,
    visit: Visit,
    payload: QuestionIn,
    now: datetime,
) -> MessageOut:
    # Lock the representative, making reservations and the daily budget atomic across workers.
    await lock_chat_user(session, user)
    existing = await session.get(PreparationMessage, payload.request_id, populate_existing=True)
    if existing:
        if existing.visit_id != visit.id or existing.question != payload.question:
            raise ApiError(409, "question_id_conflict", "Esta consulta ya se utilizó")
        if existing.status == "answered":
            return message_out(existing)
        if existing.status == "pending" and now - existing.updated_at < timedelta(seconds=90):
            raise ApiError(409, "question_pending", "UNO todavía está respondiendo esta pregunta")
        raise ApiError(503, "question_failed", "No se completó esta consulta. Vuelve a enviarla")
    check_preparation_time(visit, now, now)
    provider = getattr(ctx, "journey_provider", None)
    if provider is None:
        raise ApiError(
            503,
            "preparation_ai_unavailable",
            "Las preguntas a UNO no están disponibles. Puedes revisar tu preparación.",
        )
    await check_chat_budget(session, user, now, limit_code="preparation_question_limit")
    context = await preparation_context(session, visit)
    # The provider sees relevant source text, no raw transcripts, location or contact details.
    history = []
    for row in (await answered_messages(session, visit.id))[-5:]:
        history.extend(
            [
                {"role": "user", "content": row.question},
                {"role": "assistant", "content": row.answer or ""},
            ]
        )
    row = PreparationMessage(
        request_id=payload.request_id,
        visit_id=visit.id,
        question=payload.question,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()  # Provider I/O never holds database locks.
    try:
        answer = await asyncio.wait_for(
            provider.respond(context=context, history=history, question=payload.question),
            timeout=QUESTION_TIMEOUT_SECONDS,
        )
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("empty answer")
        answer = answer.strip()[:5000]
    except Exception:
        # Never expose/log provider exceptions: they can contain source text or credentials.
        row.status = "failed"
        row.error_code = "provider_unavailable"
        row.updated_at = clock.now()
        await session.commit()
        raise ApiError(
            503,
            "preparation_ai_unavailable",
            "UNO no pudo responder ahora. Tu preparación está guardada; intenta de nuevo.",
        ) from None
    row.status = "answered"
    row.answer = answer
    row.updated_at = clock.now()
    preparation = await locked_preparation(session, visit, row.updated_at)
    await touch(session, visit, preparation, row.updated_at)
    await session.commit()
    return message_out(row)


async def manager_metrics(
    session: AsyncSession, since: datetime, until: datetime
) -> ManagerMetricsOut:
    rows = (
        await session.execute(
            select(Visit, User, Doctor, VisitPreparation, VisitReport)
            .join(User, Visit.representative_id == User.id)
            .join(Doctor, Visit.doctor_id == Doctor.id)
            .outerjoin(VisitPreparation, VisitPreparation.visit_id == Visit.id)
            .outerjoin(VisitReport, VisitReport.visit_id == Visit.id)
            .where(Visit.scheduled_at >= since, Visit.scheduled_at < until)
            .order_by(Visit.scheduled_at)
        )
    ).all()
    ids = [row[0].id for row in rows]
    counts = dict(
        (
            await session.execute(
                select(PreparationMessage.visit_id, func.count())
                .where(
                    PreparationMessage.visit_id.in_(ids), PreparationMessage.status == "answered"
                )
                .group_by(PreparationMessage.visit_id)
            )
        ).all()
    )
    visits = []
    for visit, user, doctor, preparation, report in rows:
        feedback = feedback_for(visit.id, report)
        visits.append(
            ManagerVisitOut(
                visit_id=visit.id,
                representative_id=user.id,
                representative_name=user.full_name,
                doctor_id=doctor.id,
                doctor_name=doctor.full_name,
                scheduled_at=visit.scheduled_at,
                status=visit.status,
                active_seconds=preparation.active_seconds if preparation else 0,
                prepared_at=preparation.prepared_at if preparation else None,
                prepared_recorded_at=preparation.prepared_recorded_at if preparation else None,
                question_count=counts.get(visit.id, 0),
                score=feedback.score,
                report_status=feedback.report_status,
                rep_commitment_fulfilled=feedback.rep_commitment_fulfilled,
            )
        )
    return ManagerMetricsOut(since=since, until=until, visits=visits, rubric_version=RUBRIC_VERSION)
