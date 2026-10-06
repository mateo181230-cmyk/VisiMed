"""Chat autenticado e independiente en el módulo principal de Recomendaciones."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.context import AppContext
from uno.deps import get_ctx, get_current_user, get_session
from uno.modules.auth.models import User
from uno.modules.recommendations import service
from uno.modules.recommendations.schema import (
    RecommendationChatOut,
    RecommendationMessageOut,
    RecommendationQuestionIn,
)

router = APIRouter(prefix="/v1/intelligence/chat", tags=["intelligence"])


@router.get("", response_model=RecommendationChatOut)
async def get_chat(
    doctor_id: uuid.UUID | None = Query(default=None),
    conversation_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> RecommendationChatOut:
    return await service.chat_view(session, ctx, user, doctor_id, conversation_id)


@router.post("/questions", response_model=RecommendationMessageOut)
async def ask_chat(
    body: RecommendationQuestionIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> RecommendationMessageOut:
    return await service.answer_question(session, ctx, user, body, clock.now())
