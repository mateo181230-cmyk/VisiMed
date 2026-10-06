"""Contrato del segundo chat: datos y conversación separados de Preparar."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from uno.modules.journey.schema import AIAvailabilityOut, MessageOut, QuestionIn


class RecommendationQuestionIn(QuestionIn):
    doctor_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None


class RecommendationDoctorOut(BaseModel):
    id: uuid.UUID
    name: str


class RecommendationConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    doctor_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class RecommendationMessageOut(MessageOut):
    conversation_id: uuid.UUID


class RecommendationChatOut(BaseModel):
    messages: list[RecommendationMessageOut]
    conversation: RecommendationConversationOut | None
    conversations: list[RecommendationConversationOut]
    doctors: list[RecommendationDoctorOut]
    ai: AIAvailabilityOut
    scope: Literal["own", "team"]
    history_days: int = 365
