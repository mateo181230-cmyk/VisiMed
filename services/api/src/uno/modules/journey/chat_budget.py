"""Cuota y reserva compartidas por los dos chats, sin mantener locks durante la IA."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.errors import ApiError
from uno.modules.agenda.models import Visit
from uno.modules.auth.models import User
from uno.modules.journey.models import PreparationMessage
from uno.modules.recommendations.models import RecommendationMessage

QUESTIONS_PER_DAY = 40
QUESTION_TIMEOUT_SECONDS = 35


async def lock_chat_user(session: AsyncSession, user: User) -> None:
    await session.execute(update(User).where(User.id == user.id).values(created_at=User.created_at))


async def check_chat_budget(
    session: AsyncSession, user: User, now: datetime, *, limit_code: str
) -> None:
    since, until = clock.local_day_bounds(clock.local_date(now, user.timezone), user.timezone)
    preparation = (
        select(func.count())
        .select_from(PreparationMessage)
        .join(Visit, PreparationMessage.visit_id == Visit.id)
        .where(Visit.representative_id == user.id)
    )
    recommendations = (
        select(func.count())
        .select_from(RecommendationMessage)
        .where(RecommendationMessage.user_id == user.id)
    )
    used = (
        await session.scalar(
            preparation.where(
                PreparationMessage.created_at >= since, PreparationMessage.created_at < until
            )
        )
        or 0
    ) + (
        await session.scalar(
            recommendations.where(
                RecommendationMessage.created_at >= since, RecommendationMessage.created_at < until
            )
        )
        or 0
    )
    if used >= QUESTIONS_PER_DAY:
        raise ApiError(
            429,
            limit_code,
            "Llegaste al límite de consultas de IA de hoy. Tus datos siguen disponibles.",
        )
    pending = (
        await session.scalar(
            preparation.where(
                PreparationMessage.status == "pending",
                PreparationMessage.updated_at > now - timedelta(seconds=90),
            )
        )
        or 0
    ) + (
        await session.scalar(
            recommendations.where(
                RecommendationMessage.status == "pending",
                RecommendationMessage.updated_at > now - timedelta(seconds=90),
            )
        )
        or 0
    )
    if pending:
        raise ApiError(409, "question_pending", "Espera a que UNO termine tu consulta anterior")
