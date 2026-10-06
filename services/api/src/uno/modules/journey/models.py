"""Persistent preparation, idempotent active intervals and private questions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from uno.db import Base, UTCDateTime


class VisitPreparation(Base):
    __tablename__ = "visit_preparation"
    __table_args__ = (CheckConstraint("active_seconds >= 0", name="active_seconds"),)

    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visit.id", ondelete="CASCADE"), primary_key=True
    )
    objective: Mapped[str | None] = mapped_column(String(500), default=None)
    rep_commitment: Mapped[str | None] = mapped_column(String(500), default=None)
    objective_edited: Mapped[bool] = mapped_column(default=False)
    rep_commitment_edited: Mapped[bool] = mapped_column(default=False)
    active_seconds: Mapped[int] = mapped_column(default=0)
    prepared_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    prepared_recorded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PreparationActivity(Base):
    __tablename__ = "preparation_activity"
    __table_args__ = (
        CheckConstraint("seconds >= 0 AND seconds <= 60", name="seconds"),
        Index("ix_preparation_activity_visit_start", "visit_id", "started_at"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visit.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime] = mapped_column(UTCDateTime)
    reported_seconds: Mapped[int]
    seconds: Mapped[int]
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PreparationMessage(Base):
    __tablename__ = "preparation_message"
    __table_args__ = (
        CheckConstraint("status IN ('pending','answered','failed')", name="status"),
        Index("ix_preparation_message_visit_created", "visit_id", "created_at"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visit.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(String(1000))
    answer: Mapped[str | None] = mapped_column(String(5000), default=None)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(40), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
