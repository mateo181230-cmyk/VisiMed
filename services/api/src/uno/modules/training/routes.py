"""Rutas del módulo Entrenar (doc 04 §5.5). Necesitan conexión: la práctica no se encola."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.context import AppContext
from uno.deps import get_ctx, get_current_user, get_session, require_role
from uno.errors import ApiError
from uno.modules.auth.models import User
from uno.modules.training import service
from uno.modules.training.content import Difficulty

router = APIRouter(prefix="/v1/training", tags=["training"])
webhooks = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])
manager = APIRouter(prefix="/v1/manager", tags=["manager"])


# ------------------------------------------------------------------ esquemas


class DoctorAvailability(BaseModel):
    status: Literal["available", "unavailable", "off"]
    code: str | None
    message: str | None
    mode: Literal["tavus", "fake", "off"]


class ProfileOut(BaseModel):
    salutation: Literal["doctor", "doctora"] | None
    consent_accepted: bool
    consent_version: str
    consent_text: str


class ProgressOut(BaseModel):
    status: Literal["sin_practicar", "practicado", "aprobado"]
    attempts: int
    best: int | None
    last: int | None
    last_at: datetime | None


class QuizScore(BaseModel):
    correct: int
    total: int


class ScenarioCard(BaseModel):
    slug: str
    order: int
    title: str
    skill: str
    segment: str
    difficulty: Difficulty
    difficulty_label: str
    doctor_name: str
    doctor_specialty: str
    doctor_gender: Literal["M", "F"]
    face_id: str
    minutes: int


class ScenarioSummary(ScenarioCard):
    progress: ProgressOut
    quiz: QuizScore | None


class OverviewOut(BaseModel):
    doctor: DoctorAvailability
    profile: ProfileOut
    suggested_slug: str | None
    scenarios: list[ScenarioSummary]
    active_attempt_id: uuid.UUID | None


class LessonBlockOut(BaseModel):
    title: str
    text: str


class LessonOut(BaseModel):
    title: str
    intro: str
    blocks: list[LessonBlockOut]
    example: str
    avoid: list[str]
    sources: list[str]


class QuizOptionOut(BaseModel):
    id: str
    text: str


class QuizQuestionOut(BaseModel):
    id: str
    question: str
    options: list[QuizOptionOut]


class LastQuiz(QuizScore):
    at: datetime


class AttemptRow(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
    total: int | None
    band: str | None
    approved: bool | None


class ApprovalOut(BaseModel):
    min_total: int
    min_competencies: dict[str, int]
    blocking_errors: list[str]


class ScenarioDetailOut(ScenarioCard):
    promise: str
    instruction: str
    objective: str
    barrier: str
    expected_close: str
    lesson: LessonOut
    quiz: list[QuizQuestionOut]
    last_quiz: LastQuiz | None
    progress: ProgressOut
    attempts: list[AttemptRow]
    doctor: DoctorAvailability
    profile: ProfileOut
    approval: ApprovalOut


class QuizIn(BaseModel):
    answers: dict[str, str] = Field(max_length=20)


class QuizAnswerOut(BaseModel):
    question_id: str
    chosen: str
    correct_option: str
    is_correct: bool
    explanation: str
    source: str
    skill: str


class QuizResultOut(BaseModel):
    correct: int
    total: int
    passed: bool
    message: str
    results: list[QuizAnswerOut]


class ProfileIn(BaseModel):
    salutation: Literal["doctor", "doctora"] | None = None
    accept_consent: bool = False


class AttemptIn(BaseModel):
    scenario_slug: str = Field(max_length=60)
    audio_only: bool = False


class CompetencyOut(BaseModel):
    id: str
    name: str
    score: int
    max: int
    comment: str


class CriticalErrorOut(BaseModel):
    id: str
    text: str
    kind: Literal["compliance", "ejecucion"]


class CaseCheckOut(BaseModel):
    id: str
    text: str
    value: Literal["si", "parcial", "no"]


class KeyMomentOut(BaseModel):
    turn: int
    quote: str
    why: str


class BestResponseOut(BaseModel):
    id: str
    text: str
    source: str
    area: str


class RequirementOut(BaseModel):
    id: str
    text: str
    met: bool


class TrainingAssessmentOut(BaseModel):
    approved: bool
    requirements: list[RequirementOut]
    diagnosis: str
    focus: str
    practice: str


class BandOut(BaseModel):
    level: Literal["sobresaliente", "bueno", "intermedio", "deficiente"]
    label: str


class EvaluationOut(BaseModel):
    method: str
    preliminary: bool
    total: int
    max: int
    band: BandOut
    competencies: list[CompetencyOut]
    critical_errors: list[CriticalErrorOut]
    case_checks: list[CaseCheckOut]
    strengths: list[str]
    improvements: list[str]
    recommendation: str
    key_moment: KeyMomentOut | None
    best_response: BestResponseOut | None
    feedback: str
    training: TrainingAssessmentOut
    quiz: QuizScore | None
    turns: int


class TranscriptLine(BaseModel):
    role: Literal["rep", "doctor"]
    text: str


class AttemptOut(BaseModel):
    id: uuid.UUID
    scenario_slug: str
    scenario_title: str
    doctor_name: str
    doctor_specialty: str
    face_id: str | None
    status: Literal["starting", "live", "ended", "evaluated", "failed", "no_transcript"]
    mode: str
    conversation_url: str | None
    audio_only: bool
    max_seconds: int
    greeting: str
    created_at: datetime
    ended_at: datetime | None
    error_code: str | None
    evaluation: EvaluationOut | None
    delta: int | None
    transcript: list[TranscriptLine]


# ------------------------------------------------------------------ visitador


@router.get("/overview", response_model=OverviewOut)
async def get_overview(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> dict[str, Any]:
    return await service.overview(session, ctx, user, clock.now())


@router.get("/scenarios/{slug}", response_model=ScenarioDetailOut)
async def get_scenario(
    slug: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> dict[str, Any]:
    return await service.scenario_detail(session, ctx, user, slug, clock.now())


@router.post("/scenarios/{slug}/quiz", response_model=QuizResultOut)
async def post_quiz(
    slug: str,
    body: QuizIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await service.submit_quiz(session, user, slug, body.answers, clock.now())


@router.put("/profile", response_model=ProfileOut)
async def put_profile(
    body: ProfileIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await service.update_profile(
        session,
        user,
        clock.now(),
        salutation=body.salutation,
        accept_consent=body.accept_consent,
    )


@router.post("/attempts", response_model=AttemptOut, status_code=201)
async def post_attempt(
    body: AttemptIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> dict[str, Any]:
    now = clock.now()
    attempt = await service.start_attempt(
        session, ctx, user, body.scenario_slug, now, audio_only=body.audio_only
    )
    return await service.attempt_view(session, ctx, user, attempt.id, now)


@router.get("/attempts/{attempt_id}", response_model=AttemptOut)
async def get_attempt(
    attempt_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> dict[str, Any]:
    return await service.attempt_view(session, ctx, user, attempt_id, clock.now())


@router.post("/attempts/{attempt_id}/end", response_model=AttemptOut)
async def post_end(
    attempt_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> dict[str, Any]:
    now = clock.now()
    await service.end_attempt(session, ctx, user, attempt_id, now)
    return await service.attempt_view(session, ctx, user, attempt_id, now)


# ------------------------------------------------------------------ Tavus


@webhooks.post("/tavus/{token}", include_in_schema=False)
async def tavus_webhook(
    token: str, request: Request, ctx: AppContext = Depends(get_ctx)
) -> dict[str, Any]:
    """Tavus no firma sus avisos: el token de la URL (uno por práctica) es la autenticación."""
    try:
        body = await request.json()
    except ValueError:
        raise ApiError(400, "invalid_body", "Cuerpo inválido") from None
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_body", "Cuerpo inválido")
    outcome = await service.handle_webhook(ctx, token, body, clock.now())
    return {"ok": True, "outcome": outcome}


# ------------------------------------------------------------------ gerencia


class ScenarioProgressRow(BaseModel):
    slug: str
    title: str
    status: Literal["sin_practicar", "practicado", "aprobado"]
    attempts: int
    first: int | None
    best: int | None
    last: int | None
    last_at: datetime | None
    weakest: str | None
    compliance_errors: int


class TeamMemberRow(BaseModel):
    user_id: uuid.UUID
    full_name: str
    scenarios: list[ScenarioProgressRow]


@manager.get("/training", response_model=list[TeamMemberRow])
async def get_team_training(
    _: User = Depends(require_role("manager", "admin")),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await service.team_summary(session)
