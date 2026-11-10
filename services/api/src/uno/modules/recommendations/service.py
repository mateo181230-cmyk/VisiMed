"""Recomendaciones sobre evidencia autorizada; no modifica visitas ni reportes."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.context import AppContext
from uno.errors import ApiError, not_found
from uno.modules.auth.models import User
from uno.modules.calls.intelligence import PilotSnapshot, snapshot
from uno.modules.journey.chat_budget import (
    QUESTION_TIMEOUT_SECONDS,
    check_chat_budget,
    lock_chat_user,
)
from uno.modules.journey.models import VisitPreparation
from uno.modules.journey.schema import AIAvailabilityOut
from uno.modules.recommendations.models import RecommendationConversation, RecommendationMessage
from uno.modules.recommendations.schema import (
    RecommendationChatOut,
    RecommendationConversationOut,
    RecommendationDoctorOut,
    RecommendationMessageOut,
    RecommendationQuestionIn,
)

REPORT_FIELDS = (
    "summary",
    "doctor_interest",
    "objection",
    "current_preference",
    "representative_commitment",
    "previous_commitment_fulfilled",
    "doctor_commitment",
    "next_action",
    "next_visit_objective",
    "next_visit_date",
    "objective_progress",
)


def audience_for(user: User) -> Literal["own", "team"]:
    return "team" if user.role in ("admin", "manager") else "own"


def validate_doctor(data: PilotSnapshot, doctor_id: uuid.UUID | None) -> None:
    if doctor_id is not None and not any(d.id == doctor_id for d in data.doctors):
        raise not_found("No encontramos este médico en tus datos disponibles")


def message_out(row: RecommendationMessage) -> RecommendationMessageOut:
    return RecommendationMessageOut(
        request_id=row.request_id,
        conversation_id=row.conversation_id,
        question=row.question,
        answer=row.answer or "",
        created_at=row.created_at,
    )


async def messages(
    session: AsyncSession, user: User, conversation_id: uuid.UUID, limit: int | None = None
) -> list[RecommendationMessage]:
    rows = (
        await session.scalars(
            select(RecommendationMessage)
            .where(
                RecommendationMessage.user_id == user.id,
                RecommendationMessage.audience == audience_for(user),
                RecommendationMessage.conversation_id == conversation_id,
                RecommendationMessage.status == "answered",
            )
            .order_by(
                RecommendationMessage.created_at.desc(), RecommendationMessage.request_id.desc()
            )
            .limit(limit)
        )
    ).all()
    return list(reversed(rows))


def conversation_out(row: RecommendationConversation) -> RecommendationConversationOut:
    return RecommendationConversationOut(
        id=row.id,
        title=row.title,
        doctor_id=row.doctor_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def own_conversation(
    session: AsyncSession, user: User, conversation_id: uuid.UUID
) -> RecommendationConversation:
    row = await session.get(RecommendationConversation, conversation_id, populate_existing=True)
    if row is None or row.user_id != user.id or row.audience != audience_for(user):
        raise not_found("No encontramos este chat")
    return row


async def chat_view(
    session: AsyncSession,
    ctx: AppContext,
    user: User,
    doctor_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None = None,
) -> RecommendationChatOut:
    data = await snapshot(history_days=365, user=user, session=session)
    validate_doctor(data, doctor_id)
    conversation = None
    history = []
    if conversation_id is not None:
        conversation = await own_conversation(session, user, conversation_id)
        validate_doctor(data, conversation.doctor_id)
        history = await messages(session, user, conversation.id)
    # Abrir el módulo inicia un chat vacío. El historial se abre solo por elección del usuario.
    conversations = (
        await session.scalars(
            select(RecommendationConversation)
            .where(
                RecommendationConversation.user_id == user.id,
                RecommendationConversation.audience == audience_for(user),
                RecommendationConversation.doctor_id.is_(None)
                | RecommendationConversation.doctor_id.in_([d.id for d in data.doctors]),
            )
            .order_by(
                RecommendationConversation.updated_at.desc(), RecommendationConversation.id.desc()
            )
            .limit(100)
        )
    ).all()
    provider = ctx.recommendations_provider
    return RecommendationChatOut(
        messages=[message_out(row) for row in history],
        conversation=conversation_out(conversation) if conversation else None,
        conversations=[conversation_out(row) for row in conversations],
        doctors=[RecommendationDoctorOut(id=d.id, name=d.name) for d in data.doctors],
        ai=AIAvailabilityOut(
            available=provider is not None, mode=provider.name if provider else "off"
        ),
        scope=audience_for(user),
    )


async def context_for(
    session: AsyncSession, user: User, doctor_id: uuid.UUID | None
) -> dict[str, Any]:
    data = await snapshot(history_days=365, user=user, session=session)
    validate_doctor(data, doctor_id)
    doctors = {d.id: d for d in data.doctors}
    lines = {line.id: line.name for line in data.lines}
    visits = [v for v in data.visits if doctor_id is None or v.doctor_id == doctor_id]
    by_id = {v.id: v for v in visits}
    upcoming = sorted((v for v in visits if v.status == "scheduled"), key=lambda v: v.scheduled_at)
    reports = sorted(
        (r for r in data.reports if r.visit_id in by_id and r.status == "confirmed"),
        key=lambda r: r.confirmed_at or r.updated_at,
        reverse=True,
    )
    future = upcoming[:8]
    prep_rows = (
        await session.scalars(
            select(VisitPreparation).where(VisitPreparation.visit_id.in_([v.id for v in future]))
        )
    ).all()
    prep = {row.visit_id: row for row in prep_rows}
    recent = []
    for report in reports[:5]:
        visit = by_id[report.visit_id]
        evidence: dict[str, Any] = {}
        for key in REPORT_FIELDS:
            field = report.fields.get(key)
            if field is None or field.confidence == "low":
                continue
            value = field.value
            if isinstance(value, str) and value.strip():
                evidence[key] = value.strip()[: 360 if key == "summary" else 180]
            elif isinstance(value, (bool, int)):
                evidence[key] = value
        snc_field = report.fields.get("snc_report_json")
        if snc_field and snc_field.value:
            from uno.modules.calls.snc_report import SNCReport
            try:
                snc = SNCReport.model_validate_json(snc_field.value)
                evidence["products"] = [{"name":p.name,"objective":(p.objective or "")[:180],
                    "achievement":p.achievement,"evidence":(p.evidence or "")[:180],"barriers":[b[:100] for b in p.barriers or []][:3]}
                    for p in snc.products]
                evidence["referrals"] = [{"destination":r.destination[:120],"products":r.products} for r in (snc.referrals or [])[:5]]
                evidence["commitments"] = [{"owner":c.owner,"action":c.action[:200],"due_date":str(c.due_date) if c.due_date else None} for c in (snc.commitments or [])[:5]]
            except ValueError:
                pass  # An invalid historical structure is not evidence for the agent.
        recent.append(
            {
                "doctor": doctors[visit.doctor_id].name,
                "line": lines.get(visit.primary_line_id),
                "visit_at": visit.scheduled_at.isoformat(),
                "status": "confirmed",
                "evidence": evidence,
            }
        )
    selected = doctors.get(doctor_id) if doctor_id else None
    context: dict[str, Any] = {
        "scope": audience_for(user),
        "timezone": user.timezone,
        "now": data.now.isoformat(),
        "history_since": data.history_since.isoformat(),
        "selected_doctor": selected.name if selected else None,
        "counts": {
            "visits": len(visits),
            "scheduled": len(upcoming),
            "confirmed_reports": len(reports),
        },
        "sample_limits": {"upcoming_visits": 8, "confirmed_reports": 5, "doctors": 12},
        "doctors": [
            {"name": d.name, "specialty": d.specialty, "institution": d.institution}
            for d in (list(doctors.values())[:12] if selected is None else [selected])
        ],
        "upcoming_visits": [
            {
                "doctor": doctors[v.doctor_id].name,
                "institution": doctors[v.doctor_id].institution,
                "scheduled_at": v.scheduled_at.isoformat(),
                "line": lines.get(v.primary_line_id),
                "objective": prep[v.id].objective if v.id in prep else None,
                "representative_commitment": prep[v.id].rep_commitment if v.id in prep else None,
            }
            for v in future
        ],
        "recent_confirmed_reports": recent,
        "esomed_connected": False,
    }
    # Mantener JSON completo dentro del límite del proveedor, sin cortar evidencias a medias.
    samples = ("doctors", "upcoming_visits", "recent_confirmed_reports")
    while len(json.dumps(context, ensure_ascii=False)) > 11_500:
        candidates = [key for key in samples if len(context[key]) > 1]
        if not candidates:
            break
        longest = max(candidates, key=lambda key: len(json.dumps(context[key], ensure_ascii=False)))
        context[longest].pop()
    context["sample_sizes"] = {key: len(context[key]) for key in samples}
    return context


async def answer_question(
    session: AsyncSession,
    ctx: AppContext,
    user: User,
    payload: RecommendationQuestionIn,
    now: datetime,
) -> RecommendationMessageOut:
    await lock_chat_user(session, user)
    existing = await session.get(RecommendationMessage, payload.request_id, populate_existing=True)
    if existing:
        if existing.user_id != user.id or existing.audience != audience_for(user):
            raise not_found("No encontramos esta consulta")
        if (
            existing.question != payload.question
            or existing.doctor_id != payload.doctor_id
            or (
                payload.conversation_id is not None
                and existing.conversation_id != payload.conversation_id
            )
        ):
            raise ApiError(409, "question_id_conflict", "Esta consulta ya se utilizó")
        await own_conversation(session, user, existing.conversation_id)
        await context_for(session, user, existing.doctor_id)
        if existing.status == "answered":
            return message_out(existing)
        if existing.status == "pending" and now - existing.updated_at < timedelta(seconds=90):
            raise ApiError(409, "question_pending", "UNO todavía está respondiendo esta pregunta")
        raise ApiError(503, "question_failed", "No se completó esta consulta. Vuelve a enviarla")
    provider = ctx.recommendations_provider
    if provider is None:
        raise ApiError(
            503,
            "recommendation_ai_unavailable",
            "El chat no está disponible ahora. Puedes consultar tus recomendaciones.",
        )
    await check_chat_budget(session, user, now, limit_code="recommendation_question_limit")
    context = await context_for(session, user, payload.doctor_id)
    conversation_id = payload.conversation_id or payload.request_id
    conversation = await session.get(RecommendationConversation, conversation_id)
    if conversation is not None:
        conversation = await own_conversation(session, user, conversation_id)
        if conversation.doctor_id != payload.doctor_id:
            raise ApiError(
                409, "chat_context_conflict", "Este chat tiene otro contexto. Inicia un nuevo chat."
            )
    else:
        conversation = RecommendationConversation(
            id=conversation_id,
            user_id=user.id,
            doctor_id=payload.doctor_id,
            audience=audience_for(user),
            title=" ".join(payload.question.split())[:80],
            created_at=now,
            updated_at=now,
        )
        session.add(conversation)
        await session.flush()
    history = []
    for prior in await messages(session, user, conversation_id, limit=5):
        history.extend(
            [
                {"role": "user", "content": prior.question},
                {"role": "assistant", "content": prior.answer or ""},
            ]
        )
    row = RecommendationMessage(
        request_id=payload.request_id,
        conversation_id=conversation_id,
        user_id=user.id,
        doctor_id=payload.doctor_id,
        audience=audience_for(user),
        question=payload.question,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    try:
        answer = await asyncio.wait_for(
            provider.respond(context=context, history=history, question=payload.question),
            timeout=QUESTION_TIMEOUT_SECONDS,
        )
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("empty answer")
    except Exception:
        row.status = "failed"
        row.error_code = "provider_unavailable"
        row.updated_at = clock.now()
        conversation.updated_at = row.updated_at
        await session.commit()
        raise ApiError(
            503,
            "recommendation_ai_unavailable",
            "UNO no pudo responder ahora. Conserva tu pregunta e intenta de nuevo.",
        ) from None
    row.status = "answered"
    row.answer = answer.strip()[:5000]
    row.updated_at = clock.now()
    conversation.updated_at = row.updated_at
    await session.commit()
    return message_out(row)
