"""Authenticated preparation and feedback; manager endpoints expose aggregates, not chat."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.context import AppContext
from uno.deps import get_ctx, get_session, require_role
from uno.errors import ApiError
from uno.modules.auth.models import User
from uno.modules.auth.permissions import representative_ids
from uno.modules.calls.models import VisitReport
from uno.modules.journey import service
from uno.modules.journey.feedback import feedback_for
from uno.modules.journey.schema import (
    ActivityIn,
    FeedbackOut,
    ManagerMetricsOut,
    MessageOut,
    PreparationOut,
    PreparationPatch,
    QuestionIn,
)

router = APIRouter(prefix="/v1", tags=["journey"])


@router.get("/visits/{visit_id}/preparation", response_model=PreparationOut)
async def get_preparation(
    visit_id: uuid.UUID,
    user: User = Depends(require_role("rep", "admin")),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PreparationOut:
    visit = await service.own_visit(session, user, visit_id)
    return await service.preparation_view(session, ctx, visit)


@router.patch("/visits/{visit_id}/preparation", response_model=PreparationOut)
async def patch_preparation(
    visit_id: uuid.UUID,
    body: PreparationPatch,
    user: User = Depends(require_role("rep", "admin")),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PreparationOut:
    visit = await service.own_visit(session, user, visit_id)
    now = clock.now()
    await service.update_preparation(session, visit, body, occurred_at=now, now=now)
    await session.commit()
    return await service.preparation_view(session, ctx, visit)


@router.post("/visits/{visit_id}/preparation/prepared", response_model=PreparationOut)
async def mark_prepared(
    visit_id: uuid.UUID,
    user: User = Depends(require_role("rep", "admin")),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PreparationOut:
    visit = await service.own_visit(session, user, visit_id)
    now = clock.now()
    await service.mark_prepared(session, visit, occurred_at=now, now=now)
    await session.commit()
    return await service.preparation_view(session, ctx, visit)


@router.post("/visits/{visit_id}/preparation/activity", response_model=PreparationOut)
async def record_activity(
    visit_id: uuid.UUID,
    body: ActivityIn,
    user: User = Depends(require_role("rep", "admin")),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PreparationOut:
    visit = await service.own_visit(session, user, visit_id)
    await service.record_activity(session, visit, body, event_id=body.event_id, now=clock.now())
    await session.commit()
    return await service.preparation_view(session, ctx, visit)


@router.post("/visits/{visit_id}/preparation/questions", response_model=MessageOut)
async def ask_preparation(
    visit_id: uuid.UUID,
    body: QuestionIn,
    user: User = Depends(require_role("rep", "admin")),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> MessageOut:
    visit = await service.own_visit(session, user, visit_id)
    return await service.answer_question(session, ctx, user, visit, body, clock.now())


@router.get("/visits/{visit_id}/feedback", response_model=FeedbackOut)
async def get_feedback(
    visit_id: uuid.UUID,
    user: User = Depends(require_role("rep", "admin")),
    session: AsyncSession = Depends(get_session),
) -> FeedbackOut:
    visit = await service.own_visit(session, user, visit_id)
    report = await session.get(VisitReport, visit.id)
    return feedback_for(visit.id, report)


@router.get("/journey/metrics", response_model=ManagerMetricsOut)
async def preparation_metrics(
    since: AwareDatetime | None = Query(default=None),
    until: AwareDatetime | None = Query(default=None),
    user: User = Depends(require_role("manager", "admin")),
    session: AsyncSession = Depends(get_session),
) -> ManagerMetricsOut:
    now = clock.now()
    first = since or now - timedelta(days=30)
    last = until or now + timedelta(days=14)
    if last <= first or last - first > timedelta(days=366):
        raise ApiError(422, "invalid_metrics_window", "Elige un período de hasta un año")
    return await service.manager_metrics(session, first, last, representative_ids(user))
