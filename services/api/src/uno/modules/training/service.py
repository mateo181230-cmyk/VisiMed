"""Entrenar: casos de uso (doc 04 §5.5–§5.6).

El ciclo de una práctica: ``start_attempt`` crea la conversación en el proveedor → el celular se une
por WebRTC → ``end_attempt`` (o el tiempo, o Tavus) la termina → la transcripción llega por webhook
o por consulta (``refresh_attempt`` / ``run_training_cycle``) → ``_finalize`` guarda los turnos y la
evaluación. Todo es idempotente: un webhook repetido o una consulta concurrente no duplican nada.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock, events
from uno.context import AppContext
from uno.errors import ApiError, not_found
from uno.modules.auth.models import User
from uno.modules.training import evaluation, prompts
from uno.modules.training import rules as rules_mod
from uno.modules.training.content import Catalog, Scenario, get_catalog
from uno.modules.training.models import (
    ACTIVE_STATUSES,
    PracticeAttempt,
    PracticeEvaluation,
    PracticeTurn,
    TrainingProfile,
    TrainingQuizResult,
    TrainingScenarioVersion,
)
from uno.modules.training.provider import (
    ConversationRequest,
    ProviderError,
    Transcript,
    TranscriptTurn,
)

log = logging.getLogger("uno.training")

FAILURE_MEMORY = timedelta(minutes=5)  # tras un «sin créditos», no se insiste durante este tiempo
PROBE_EVERY = FAILURE_MEMORY  # consulta de disponibilidad, como mucho una vez en ese lapso
PROBE_TIMEOUT_SECONDS = 8
STARTING_TIMEOUT = timedelta(seconds=90)
LIVE_GRACE = timedelta(minutes=2)  # margen sobre la duración máxima antes de darla por terminada
POLL_EVERY = timedelta(seconds=3)

UNAVAILABLE_MESSAGE = (
    "El médico virtual no está disponible por ahora. Mientras tanto puedes repasar la preparación "
    "y hacer el formulario; tu avance queda guardado. Inténtalo más tarde."
)
MESSAGES = {
    "off": "El médico virtual todavía no está activo. Mientras tanto puedes hacer la preparación.",
    "no_credits": UNAVAILABLE_MESSAGE,
    "auth": UNAVAILABLE_MESSAGE,
    "not_published": UNAVAILABLE_MESSAGE,
    "rejected": UNAVAILABLE_MESSAGE,
    "busy": "El médico virtual está atendiendo otras prácticas. Intenta de nuevo en un minuto.",
    "unavailable": (
        "No pudimos conectar con el médico virtual. Revisa tu conexión e inténtalo de nuevo."
    ),
}
STICKY_FAILURES = frozenset({"no_credits", "auth", "not_published"})


# --------------------------------------------------------------------------- disponibilidad


def availability(ctx: AppContext, now: datetime) -> dict[str, Any]:
    """¿Se puede hablar con el médico? Recuerda un fallo «duro» (sin créditos) unos minutos."""
    if ctx.conversation_provider is None:
        return {"status": "off", "code": "off", "message": MESSAGES["off"], "mode": "off"}
    mode = ctx.conversation_provider.name
    known = ctx.training_state.get("known")
    if known and known[0] and now - known[1] < FAILURE_MEMORY:
        code = known[0]
        return {"status": "unavailable", "code": code, "message": MESSAGES[code], "mode": mode}
    return {"status": "available", "code": None, "message": None, "mode": mode}


def _remember(ctx: AppContext, code: str | None, now: datetime) -> None:
    """Lo último que se supo del proveedor, por una consulta o por una visita real."""
    ctx.training_state["known"] = (code if code in STICKY_FAILURES else None, now)


async def check_availability(
    session: AsyncSession, ctx: AppContext, now: datetime
) -> dict[str, Any]:
    """Disponibilidad al abrir Entrenar: si lo que se sabe ya es viejo, se consulta al proveedor.

    Con Tavus es una conversación en ``test_mode`` (sin costo; se borra enseguida). Así el visitador
    ve «no disponible» antes de dar permisos y aceptar condiciones, no después.
    """
    provider = ctx.conversation_provider
    known = ctx.training_state.get("known")
    if provider is None or (known and now - known[1] < PROBE_EVERY):
        return availability(ctx, now)
    lock = ctx.training_state.setdefault("probe_lock", asyncio.Lock())
    async with lock:
        known = ctx.training_state.get("known")
        if not known or now - known[1] >= PROBE_EVERY:
            pal_id = None
            if provider.name == "tavus":
                pal_id = (
                    await session.execute(
                        select(TrainingScenarioVersion.tavus_pal_id)
                        .where(
                            TrainingScenarioVersion.retired_at.is_(None),
                            TrainingScenarioVersion.tavus_pal_id.is_not(None),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
            code: str | None = "not_published"
            if pal_id or provider.name != "tavus":
                try:
                    code = await asyncio.wait_for(provider.probe(pal_id), PROBE_TIMEOUT_SECONDS)
                except ProviderError as exc:
                    code = exc.code
                except TimeoutError:
                    code = None  # sin respuesta a tiempo: no se bloquea; la visita dirá si falla
            if code:
                log.info("consulta de disponibilidad del médico virtual: %s", code)
            _remember(ctx, code, now)
    return availability(ctx, now)


# ----------------------------------------------------------------------- perfil y consentimiento


def _consent_version(catalog: Catalog) -> str:
    return catalog.common.consent["version"]


async def get_profile(session: AsyncSession, user_id: uuid.UUID) -> TrainingProfile | None:
    return await session.get(TrainingProfile, user_id)


def profile_view(profile: TrainingProfile | None, catalog: Catalog) -> dict[str, Any]:
    version = _consent_version(catalog)
    return {
        "salutation": profile.salutation if profile else None,
        "consent_accepted": bool(
            profile and profile.consent_accepted_at and profile.consent_version == version
        ),
        "consent_version": version,
        "consent_text": catalog.common.consent["text"],
    }


async def update_profile(
    session: AsyncSession,
    user: User,
    now: datetime,
    *,
    salutation: str | None,
    accept_consent: bool,
) -> dict[str, Any]:
    catalog = get_catalog()
    profile = await get_profile(session, user.id)
    if profile is None:
        profile = TrainingProfile(user_id=user.id, updated_at=now)
        session.add(profile)
    if salutation is not None:
        profile.salutation = salutation
    if accept_consent:
        profile.consent_version = _consent_version(catalog)
        profile.consent_accepted_at = now
    profile.updated_at = now
    await session.commit()
    return profile_view(profile, catalog)


# --------------------------------------------------------------------------- lectura: escenarios


async def _latest_quiz(
    session: AsyncSession, user_id: uuid.UUID, slug: str
) -> TrainingQuizResult | None:
    return (
        await session.execute(
            select(TrainingQuizResult)
            .where(TrainingQuizResult.user_id == user_id, TrainingQuizResult.scenario_slug == slug)
            .order_by(TrainingQuizResult.created_at.desc(), TrainingQuizResult.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _evaluated(
    session: AsyncSession, user_id: uuid.UUID, slug: str | None = None
) -> list[tuple[PracticeAttempt, PracticeEvaluation]]:
    query = (
        select(PracticeAttempt, PracticeEvaluation)
        .join(PracticeEvaluation, PracticeEvaluation.attempt_id == PracticeAttempt.id)
        .where(PracticeAttempt.user_id == user_id, PracticeAttempt.status == "evaluated")
        .order_by(PracticeAttempt.created_at, PracticeAttempt.id)  # UUIDv7: desempate por orden
    )
    if slug is not None:
        query = query.where(PracticeAttempt.scenario_slug == slug)
    return [(a, e) for a, e in (await session.execute(query)).all()]


def _progress(rows: list[tuple[PracticeAttempt, PracticeEvaluation]]) -> dict[str, Any]:
    if not rows:
        return {
            "status": "sin_practicar",
            "attempts": 0,
            "best": None,
            "last": None,
            "last_at": None,
        }
    approved = any(e.approved for _, e in rows)
    last_attempt, last_eval = rows[-1]
    return {
        "status": "aprobado" if approved else "practicado",
        "attempts": len(rows),
        "best": max(e.total for _, e in rows),
        "last": last_eval.total,
        "last_at": last_attempt.created_at,
    }


def _scenario_card(scenario: Scenario) -> dict[str, Any]:
    return {
        "slug": scenario.slug,
        "order": scenario.order,
        "title": scenario.title,
        "skill": scenario.skill,
        "segment": scenario.segment,
        "difficulty": scenario.difficulty,
        "difficulty_label": scenario.difficulty_label,
        "doctor_name": scenario.doctor.name,
        "doctor_specialty": scenario.doctor.specialty,
        "doctor_gender": scenario.doctor.gender,
        "face_id": scenario.casting.face_id,
        "minutes": scenario.doctor.minutes,
    }


async def overview(
    session: AsyncSession, ctx: AppContext, user: User, now: datetime
) -> dict[str, Any]:
    catalog = get_catalog()
    rows = await _evaluated(session, user.id)
    cards = []
    suggested: str | None = None
    for scenario in catalog.scenarios:
        mine = [(a, e) for a, e in rows if a.scenario_slug == scenario.slug]
        progress = _progress(mine)
        quiz = await _latest_quiz(session, user.id, scenario.slug)
        if suggested is None and progress["status"] != "aprobado":
            suggested = scenario.slug
        cards.append(
            {
                **_scenario_card(scenario),
                "progress": progress,
                "quiz": {"correct": quiz.correct, "total": quiz.total} if quiz else None,
            }
        )
    return {
        "doctor": await check_availability(session, ctx, now),
        "profile": profile_view(await get_profile(session, user.id), catalog),
        "suggested_slug": suggested,
        "scenarios": cards,
        "active_attempt_id": await _active_attempt_id(session, user.id),
    }


async def _active_attempt_id(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    return (
        await session.execute(
            select(PracticeAttempt.id).where(
                PracticeAttempt.user_id == user_id, PracticeAttempt.status.in_(ACTIVE_STATUSES)
            )
        )
    ).scalar_one_or_none()


def _require_scenario(slug: str) -> Scenario:
    scenario = get_catalog().get(slug)
    if scenario is None:
        raise not_found("Ese escenario no existe")
    return scenario


async def scenario_detail(
    session: AsyncSession, ctx: AppContext, user: User, slug: str, now: datetime
) -> dict[str, Any]:
    catalog = get_catalog()
    scenario = _require_scenario(slug)
    quiz = await _latest_quiz(session, user.id, slug)
    history = (
        (
            await session.execute(
                select(PracticeAttempt)
                .where(
                    PracticeAttempt.user_id == user.id,
                    PracticeAttempt.scenario_slug == slug,
                    PracticeAttempt.status.in_(("evaluated", "no_transcript", *ACTIVE_STATUSES)),
                )
                .order_by(PracticeAttempt.created_at.desc(), PracticeAttempt.id.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    evals = {
        e.attempt_id: e
        for e in (
            await session.execute(
                select(PracticeEvaluation).where(
                    PracticeEvaluation.attempt_id.in_([a.id for a in history])
                )
            )
        ).scalars()
    }
    rows = await _evaluated(session, user.id, slug)
    return {
        **_scenario_card(scenario),
        "promise": scenario.promise,
        "instruction": scenario.instruction,
        "objective": scenario.objective,
        "barrier": scenario.barrier.text,
        "expected_close": scenario.expected_close,
        "lesson": scenario.lesson.model_dump(),
        "quiz": [
            {
                "id": q.id,
                "question": q.question,
                "options": [{"id": o.id, "text": o.text} for o in q.options],
            }
            for q in scenario.quiz
        ],
        "last_quiz": (
            {"correct": quiz.correct, "total": quiz.total, "at": quiz.created_at} if quiz else None
        ),
        "progress": _progress(rows),
        "attempts": [
            {
                "id": a.id,
                "status": a.status,
                "created_at": a.created_at,
                "total": evals[a.id].total if a.id in evals else None,
                "band": evals[a.id].band if a.id in evals else None,
                "approved": evals[a.id].approved if a.id in evals else None,
            }
            for a in history
        ],
        "doctor": await check_availability(session, ctx, now),
        "profile": profile_view(await get_profile(session, user.id), catalog),
        "approval": scenario.approval.model_dump(),
    }


# --------------------------------------------------------------------------- formulario


async def submit_quiz(
    session: AsyncSession, user: User, slug: str, answers: dict[str, str], now: datetime
) -> dict[str, Any]:
    scenario = _require_scenario(slug)
    missing = [q.id for q in scenario.quiz if q.id not in answers]
    if missing:
        raise ApiError(422, "quiz_incomplete", "Responde todas las preguntas antes de revisar")
    results = []
    correct = 0
    for q in scenario.quiz:
        chosen = answers[q.id]
        if chosen not in {o.id for o in q.options}:
            raise ApiError(422, "quiz_invalid", "Una respuesta no corresponde a sus opciones")
        ok = chosen == q.correct_option
        correct += ok
        results.append(
            {
                "question_id": q.id,
                "chosen": chosen,
                "correct_option": q.correct_option,
                "is_correct": ok,
                "explanation": q.explanation,
                "source": q.source,
                "skill": q.skill,
            }
        )
    session.add(
        TrainingQuizResult(
            user_id=user.id,
            scenario_slug=slug,
            answers={q.id: answers[q.id] for q in scenario.quiz},
            correct=correct,
            total=len(scenario.quiz),
            created_at=now,
        )
    )
    await session.commit()
    passed = correct / len(scenario.quiz) >= evaluation.PASS_QUIZ_RATIO
    return {
        "correct": correct,
        "total": len(scenario.quiz),
        "passed": passed,
        "message": (
            "Reconoces la técnica. Ahora demuéstralo hablando con el médico."
            if passed
            else (
                "Revisa las explicaciones antes de hablar con el médico: la visita te mostrará "
                "qué ajustar."
            )
        ),
        "results": results,
    }


# --------------------------------------------------------------------------- práctica


async def _published_version(
    session: AsyncSession, catalog: Catalog, scenario: Scenario
) -> TrainingScenarioVersion | None:
    return (
        await session.execute(
            select(TrainingScenarioVersion)
            .where(
                TrainingScenarioVersion.scenario_slug == scenario.slug,
                TrainingScenarioVersion.content_hash == catalog.content_hash(scenario),
                TrainingScenarioVersion.retired_at.is_(None),
                TrainingScenarioVersion.tavus_pal_id.is_not(None),
            )
            .order_by(TrainingScenarioVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def start_attempt(
    session: AsyncSession,
    ctx: AppContext,
    user: User,
    slug: str,
    now: datetime,
    *,
    audio_only: bool = False,
) -> PracticeAttempt:
    catalog = get_catalog()
    scenario = _require_scenario(slug)
    provider = ctx.conversation_provider
    state = availability(ctx, now)
    if provider is None or state["status"] != "available":
        raise ApiError(503, "doctor_unavailable", state["message"] or UNAVAILABLE_MESSAGE)

    profile = await get_profile(session, user.id)
    if not profile_view(profile, catalog)["consent_accepted"]:
        raise ApiError(
            409, "consent_required", "Acepta las condiciones de la práctica para empezar"
        )
    assert profile is not None

    if await _active_attempt_id(session, user.id) is not None:
        raise ApiError(409, "attempt_active", "Ya tienes una visita de práctica en curso")
    start, end = clock.local_day_bounds(clock.local_date(now, user.timezone), user.timezone)
    today = (
        await session.execute(
            select(func.count())
            .select_from(PracticeAttempt)
            .where(
                PracticeAttempt.user_id == user.id,
                PracticeAttempt.created_at >= start,
                PracticeAttempt.created_at < end,
                PracticeAttempt.status != "failed",
            )
        )
    ).scalar_one()
    if today >= ctx.settings.training_attempts_per_day:
        raise ApiError(
            429,
            "daily_limit",
            f"Ya hiciste {today} prácticas hoy. Mañana puedes seguir practicando.",
        )

    version = None
    if provider.name == "tavus":
        version = await _published_version(session, catalog, scenario)
        if version is None:
            _remember(ctx, "not_published", now)
            raise ApiError(503, "doctor_unavailable", MESSAGES["not_published"])

    evaluated_before = (
        await session.execute(
            select(func.count())
            .select_from(PracticeAttempt)
            .where(
                PracticeAttempt.user_id == user.id,
                PracticeAttempt.scenario_slug == slug,
                PracticeAttempt.status == "evaluated",
            )
        )
    ).scalar_one()
    attempt_no = evaluated_before + 1
    token = secrets.token_urlsafe(32)
    attempt = PracticeAttempt(
        user_id=user.id,
        scenario_slug=slug,
        version_id=version.id if version else None,
        content_hash=catalog.content_hash(scenario),
        status="starting",
        provider=provider.name,
        webhook_token_hash=_token_hash(token),
        audio_only=audio_only,
        attempt_no=attempt_no,
        greeting=scenario.greeting(attempt_no - 1, profile.salutation),
        created_at=now,
    )
    session.add(attempt)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ApiError(409, "attempt_active", "Ya tienes una visita de práctica en curso") from None

    base = ctx.settings.tavus_callback_base_url.rstrip("/")
    request = ConversationRequest(
        pal_id=version.tavus_pal_id if version else None,
        name=f"UNO Entrenar {attempt.id}",
        context=prompts.attempt_context(
            scenario,
            first_name=prompts.first_name(user.full_name),
            salutation=profile.salutation,
            attempt_no=attempt_no,
        ),
        greeting=attempt.greeting,
        callback_url=f"{base}/v1/webhooks/tavus/{token}" if base else None,
        max_seconds=ctx.settings.training_max_call_seconds,
        audio_only=audio_only,
        scenario_slug=slug,
    )
    try:
        created = await provider.create_conversation(request)
    except ProviderError as exc:
        log.warning("no se pudo crear la conversación de práctica: %s (%s)", exc.code, exc)
        _remember(ctx, exc.code, clock.now())
        attempt.status = "failed"
        attempt.error_code = exc.code
        attempt.ended_at = clock.now()
        await session.commit()
        raise ApiError(
            503, "doctor_unavailable", MESSAGES.get(exc.code, UNAVAILABLE_MESSAGE)
        ) from None
    _remember(ctx, None, clock.now())
    attempt.status = "live"
    attempt.conversation_id = created.conversation_id
    attempt.conversation_url = created.conversation_url
    await events.emit(
        session,
        event_type="practice_attempt_started",
        occurred_at=now,
        recorded_at=clock.now(),
        actor_type="rep",
        actor_id=user.id,
        entities={"practice_attempt_id": attempt.id, "scenario": slug},
        payload={"provider": provider.name, "attempt_no": attempt_no, "audio_only": audio_only},
    )
    await session.commit()
    return attempt


async def _load_attempt(
    session: AsyncSession, user: User, attempt_id: uuid.UUID
) -> PracticeAttempt:
    attempt = await session.get(PracticeAttempt, attempt_id)
    if attempt is None or attempt.user_id != user.id:
        raise not_found("Esa práctica no existe")
    return attempt


async def end_attempt(
    session: AsyncSession, ctx: AppContext, user: User, attempt_id: uuid.UUID, now: datetime
) -> PracticeAttempt:
    attempt = await _load_attempt(session, user, attempt_id)
    if attempt.status in ACTIVE_STATUSES:
        attempt.status = "ended" if attempt.conversation_id else "failed"
        attempt.ended_at = now
        attempt.end_reason = "rep_ended"
        await session.commit()
        await _end_remote(ctx, attempt)
    await refresh_attempt(ctx, attempt.id, now, force=True)
    await session.refresh(attempt)
    return attempt


async def _end_remote(ctx: AppContext, attempt: PracticeAttempt) -> None:
    provider = ctx.conversation_provider
    if provider is None or not attempt.conversation_id:
        return
    try:
        await provider.end_conversation(attempt.conversation_id)
    except ProviderError as exc:
        log.warning("no se pudo terminar la conversación en el proveedor: %s", exc.code)


def _rule_turns(turns: list[TranscriptTurn]) -> list[rules_mod.Turn]:
    return [rules_mod.Turn(t.role, t.text) for t in turns]


async def _finalize(
    session: AsyncSession, attempt: PracticeAttempt, turns: list[TranscriptTurn], now: datetime
) -> str:
    """Guarda la transcripción y la evaluación. Solo gana quien pasa el estado de ``ended``.

    Una transcripción que llega tarde (después de darla por perdida) todavía se evalúa.
    """
    has_rep = any(t.role == "rep" and t.text.strip() for t in turns)
    target = "evaluated" if has_rep else "no_transcript"
    claimable = ("ended", "no_transcript") if has_rep else ("ended",)
    claimed = await session.execute(
        update(PracticeAttempt)
        .where(PracticeAttempt.id == attempt.id, PracticeAttempt.status.in_(claimable))
        .values(
            status=target,
            evaluated_at=now if has_rep else None,
            end_reason=attempt.end_reason or ("sin_conversacion" if not has_rep else None),
        )
    )
    if claimed.rowcount != 1:  # type: ignore[attr-defined]
        await session.rollback()
        return "already"
    for i, turn in enumerate(turns):
        session.add(
            PracticeTurn(
                attempt_id=attempt.id,
                idx=i,
                role=turn.role,
                text=turn.text[:4000],
                t=turn.t,
                duration=turn.duration,
            )
        )
    if not has_rep:
        await session.commit()
        return target
    catalog = get_catalog()
    scenario = catalog.get(attempt.scenario_slug)
    assert scenario is not None
    quiz = await _latest_quiz(session, attempt.user_id, attempt.scenario_slug)
    snapshot = evaluation.QuizSnapshot(quiz.correct, quiz.total) if quiz else None
    result = evaluation.build(catalog, scenario, _rule_turns(turns), snapshot)
    session.add(
        PracticeEvaluation(
            attempt_id=attempt.id,
            method=result["method"],
            total=result["total"],
            band=result["band"]["level"],
            approved=result["training"]["approved"],
            result=result,
            created_at=now,
        )
    )
    await events.emit(
        session,
        event_type="practice_attempt_evaluated",
        occurred_at=now,
        recorded_at=clock.now(),
        actor_type="system",
        actor_id=None,
        entities={"practice_attempt_id": attempt.id, "scenario": attempt.scenario_slug},
        payload={
            "method": result["method"],
            "total": result["total"],
            "band": result["band"]["level"],
            "approved": result["training"]["approved"],
            "turns": len(turns),
        },
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return "already"
    return target


async def refresh_attempt(
    ctx: AppContext, attempt_id: uuid.UUID, now: datetime, *, force: bool = False
) -> str:
    """Si la práctica terminó y aún no tiene transcripción, la pide al proveedor (con mesura)."""
    provider = ctx.conversation_provider
    async with ctx.sessionmaker() as session:
        attempt = await session.get(PracticeAttempt, attempt_id)
        if attempt is None or attempt.status != "ended" or not attempt.conversation_id:
            return "skip"
        if (
            not force
            and attempt.last_polled_at is not None
            and now - attempt.last_polled_at < POLL_EVERY
        ):
            return "wait"
        attempt.last_polled_at = now
        await session.commit()
        if provider is None:
            return "skip"
        try:
            transcript: Transcript = await provider.fetch_transcript(attempt.conversation_id)
        except ProviderError as exc:
            log.warning("consulta de transcripción fallida: %s", exc.code)
            return "error"
        if transcript.ready:
            return await _finalize(session, attempt, transcript.turns, now)
        timeout = timedelta(minutes=ctx.settings.training_transcript_timeout_minutes)
        if attempt.ended_at is not None and now - attempt.ended_at > timeout:
            return await _finalize(session, attempt, [], now)
        return "pending"


async def attempt_view(
    session: AsyncSession, ctx: AppContext, user: User, attempt_id: uuid.UUID, now: datetime
) -> dict[str, Any]:
    attempt = await _load_attempt(session, user, attempt_id)
    if attempt.status == "ended":
        await session.commit()  # cierra la lectura: la consulta escribe en otra sesión
        await refresh_attempt(ctx, attempt.id, now)
        await session.refresh(attempt)
    scenario = get_catalog().get(attempt.scenario_slug)
    evaluation_row = (
        await session.execute(
            select(PracticeEvaluation)
            .where(PracticeEvaluation.attempt_id == attempt.id)
            .order_by(PracticeEvaluation.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    previous = None
    if evaluation_row is not None:
        previous = (
            await session.execute(
                select(PracticeEvaluation.total)
                .join(PracticeAttempt, PracticeAttempt.id == PracticeEvaluation.attempt_id)
                .where(
                    PracticeAttempt.user_id == user.id,
                    PracticeAttempt.scenario_slug == attempt.scenario_slug,
                    PracticeAttempt.status == "evaluated",
                    PracticeAttempt.id != attempt.id,
                    or_(
                        PracticeAttempt.created_at < attempt.created_at,
                        and_(
                            PracticeAttempt.created_at == attempt.created_at,
                            PracticeAttempt.id < attempt.id,
                        ),
                    ),
                )
                .order_by(PracticeAttempt.created_at.desc(), PracticeAttempt.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    turns = (
        (
            await session.execute(
                select(PracticeTurn)
                .where(PracticeTurn.attempt_id == attempt.id)
                .order_by(PracticeTurn.idx)
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": attempt.id,
        "scenario_slug": attempt.scenario_slug,
        "scenario_title": scenario.title if scenario else attempt.scenario_slug,
        "doctor_name": scenario.doctor.name if scenario else "",
        "doctor_specialty": scenario.doctor.specialty if scenario else "",
        "face_id": scenario.casting.face_id if scenario else None,
        "status": attempt.status,
        "mode": attempt.provider,
        "conversation_url": attempt.conversation_url if attempt.status == "live" else None,
        "audio_only": attempt.audio_only,
        "max_seconds": ctx.settings.training_max_call_seconds,
        "greeting": attempt.greeting,
        "created_at": attempt.created_at,
        "ended_at": attempt.ended_at,
        "error_code": attempt.error_code,
        "evaluation": evaluation.for_display(evaluation_row.result) if evaluation_row else None,
        "delta": (
            evaluation_row.total - previous
            if evaluation_row is not None and previous is not None
            else None
        ),
        "transcript": [{"role": t.role, "text": t.text} for t in turns],
    }


# --------------------------------------------------------------------------- webhook de Tavus


async def handle_webhook(ctx: AppContext, token: str, body: dict[str, Any], now: datetime) -> str:
    async with ctx.sessionmaker() as session:
        attempt = (
            await session.execute(
                select(PracticeAttempt).where(
                    PracticeAttempt.webhook_token_hash == _token_hash(token)
                )
            )
        ).scalar_one_or_none()
        if attempt is None or str(body.get("conversation_id") or "") != (
            attempt.conversation_id or ""
        ):
            raise not_found()
        kind = str(body.get("event_type") or body.get("message_type") or "")
        props = body.get("properties") or {}
        if kind == "system.shutdown" and attempt.status in ACTIVE_STATUSES:
            attempt.status = "ended"
            attempt.ended_at = now
            attempt.end_reason = str(props.get("shutdown_reason") or "shutdown")[:80]
            await session.commit()
            return "ended"
        if kind in ("application.transcription_ready", "application.transcript_ready"):
            if attempt.status in ACTIVE_STATUSES:
                attempt.status = "ended"
                attempt.ended_at = now
                attempt.end_reason = attempt.end_reason or "transcript"
                await session.commit()
            from uno.modules.training.provider import parse_transcript

            return await _finalize(session, attempt, parse_transcript(props.get("transcript")), now)
        return "ignored"


# --------------------------------------------------------------------------- trabajador


async def run_training_cycle(ctx: AppContext, now: datetime | None = None) -> dict[str, int]:
    """Cierra prácticas colgadas y recoge transcripciones pendientes. Idempotente."""
    now = now or clock.now()
    stats: dict[str, int] = {}
    max_live = timedelta(seconds=ctx.settings.training_max_call_seconds) + LIVE_GRACE
    async with ctx.sessionmaker() as session:
        stuck = (
            (
                await session.execute(
                    select(PracticeAttempt).where(
                        PracticeAttempt.status.in_(ACTIVE_STATUSES),
                    )
                )
            )
            .scalars()
            .all()
        )
        for attempt in stuck:
            if attempt.status == "starting" and now - attempt.created_at > STARTING_TIMEOUT:
                attempt.status, attempt.error_code, attempt.ended_at = (
                    "failed",
                    "start_timeout",
                    now,
                )
                stats["failed"] = stats.get("failed", 0) + 1
            elif attempt.status == "live" and now - attempt.created_at > max_live:
                attempt.status, attempt.ended_at, attempt.end_reason = "ended", now, "timeout"
                stats["timed_out"] = stats.get("timed_out", 0) + 1
                await _end_remote(ctx, attempt)
        await session.commit()
        pending = (
            (
                await session.execute(
                    select(PracticeAttempt.id).where(PracticeAttempt.status == "ended")
                )
            )
            .scalars()
            .all()
        )
    for attempt_id in pending:
        outcome = await refresh_attempt(ctx, attempt_id, now)
        stats[outcome] = stats.get(outcome, 0) + 1
    return {k: v for k, v in stats.items() if k not in ("wait", "pending", "skip") or v}


# --------------------------------------------------------------------------- gerencia


async def team_summary(session: AsyncSession) -> list[dict[str, Any]]:
    """Persona × escenario: intentos, mejor y último puntaje, aprobado (doc 04 §5.11)."""
    catalog = get_catalog()
    reps = (
        (
            await session.execute(
                select(User)
                .where(User.role == "rep", User.is_active.is_(True))
                .order_by(User.full_name)
            )
        )
        .scalars()
        .all()
    )
    rows = (
        await session.execute(
            select(PracticeAttempt, PracticeEvaluation)
            .join(PracticeEvaluation, PracticeEvaluation.attempt_id == PracticeAttempt.id)
            .where(PracticeAttempt.status == "evaluated")
            .order_by(PracticeAttempt.created_at, PracticeAttempt.id)
        )
    ).all()
    by_user: dict[uuid.UUID, list[tuple[PracticeAttempt, PracticeEvaluation]]] = {}
    for attempt, ev in rows:
        by_user.setdefault(attempt.user_id, []).append((attempt, ev))
    summary = []
    for rep in reps:
        mine = by_user.get(rep.id, [])
        scenarios = []
        for scenario in catalog.scenarios:
            subset = [(a, e) for a, e in mine if a.scenario_slug == scenario.slug]
            progress = _progress(subset)
            weakest = None
            if subset:
                comps = subset[-1][1].result.get("competencies", [])
                if comps:
                    low = min(comps, key=lambda c: c["score"])
                    weakest = low["name"]
            compliance = sum(
                1
                for _, e in subset
                for err in e.result.get("critical_errors", [])
                if err.get("kind") == "compliance"
            )
            scenarios.append(
                {
                    "slug": scenario.slug,
                    "title": scenario.title,
                    **progress,
                    "first": subset[0][1].total if subset else None,
                    "weakest": weakest,
                    "compliance_errors": compliance,
                }
            )
        summary.append({"user_id": rep.id, "full_name": rep.full_name, "scenarios": scenarios})
    return summary
