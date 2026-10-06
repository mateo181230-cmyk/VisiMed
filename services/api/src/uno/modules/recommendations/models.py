"""Historial independiente del chat por visita; privado por usuario y alcance."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from uno.db import Base, UTCDateTime


class RecommendationConversation(Base):
    __tablename__ = "recommendation_conversation"
    __table_args__ = (
        CheckConstraint("audience IN ('own','team')", name="audience"),
        Index("ix_recommendation_conversation_user_updated", "user_id", "audience", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("doctor.id", ondelete="SET NULL"), default=None
    )
    audience: Mapped[str] = mapped_column(String(4))
    title: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class RecommendationMessage(Base):
    __tablename__ = "recommendation_message"
    __table_args__ = (
        CheckConstraint("status IN ('pending','answered','failed')", name="status"),
        CheckConstraint("audience IN ('own','team')", name="audience"),
        Index("ix_recommendation_message_user_created", "user_id", "audience", "created_at"),
        Index("ix_recommendation_message_conversation_created", "conversation_id", "created_at"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendation_conversation.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("doctor.id", ondelete="SET NULL"), default=None
    )
    audience: Mapped[str] = mapped_column(String(4))
    question: Mapped[str] = mapped_column(String(1000))
    answer: Mapped[str | None] = mapped_column(String(5000), default=None)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(40), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
