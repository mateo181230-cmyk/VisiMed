"""Tablas del módulo Entrenar (doc 04 §5.4). Todo cuelga del visitador (``app_user``).

- ``TrainingProfile``: trato («doctor» / «doctora») y aceptación del consentimiento de la práctica.
- ``TrainingQuizResult``: cada envío del formulario de preparación (solo diagnóstico).
- ``TrainingScenarioVersion``: lo publicado en Tavus. Inmutable: publicar crea una fila nueva.
- ``PracticeAttempt``: una visita con el médico virtual. Ciclo: ``starting`` → ``live`` →
  ``ended`` → ``evaluated``; ``failed`` si no arrancó y ``no_transcript`` si no quedó
  conversación. Solo ``evaluated`` cuenta como intento. Un visitador tiene como mucho una práctica
  viva a la vez.
- ``PracticeTurn``: la transcripción, un turno por fila (datos personales: nunca a logs ni eventos).
- ``PracticeEvaluation``: una por método (hoy «reglas»; mañana también el juez).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from uno.db import Base, JSONType, UTCDateTime
from uno.ids import uuid7

ATTEMPT_STATUSES = ("starting", "live", "ended", "evaluated", "failed", "no_transcript")
ACTIVE_STATUSES = ("starting", "live")


class TrainingProfile(Base):
    __tablename__ = "training_profile"
    __table_args__ = (CheckConstraint("salutation IN ('doctor','doctora')", name="salutation"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    salutation: Mapped[str] = mapped_column(String(10), default="doctor")
    consent_version: Mapped[str | None] = mapped_column(String(40), default=None)
    consent_accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TrainingQuizResult(Base):
    __tablename__ = "training_quiz_result"
    __table_args__ = (
        Index("ix_training_quiz_result_user_scenario", "user_id", "scenario_slug", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    scenario_slug: Mapped[str] = mapped_column(String(60))
    answers: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    correct: Mapped[int]
    total: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TrainingScenarioVersion(Base):
    __tablename__ = "training_scenario_version"
    __table_args__ = (
        UniqueConstraint("scenario_slug", "version", name="uq_training_scenario_version_slug_ver"),
        Index("ix_training_scenario_version_hash", "scenario_slug", "content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    scenario_slug: Mapped[str] = mapped_column(String(60))
    version: Mapped[int]
    content_hash: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(20))
    tavus_pal_id: Mapped[str | None] = mapped_column(String(40), default=None)
    face_id: Mapped[str] = mapped_column(String(40))
    voice_id: Mapped[str] = mapped_column(String(60))
    published_at: Mapped[datetime] = mapped_column(UTCDateTime)
    retired_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class PracticeAttempt(Base):
    __tablename__ = "practice_attempt"
    __table_args__ = (
        CheckConstraint("status IN ('" + "','".join(ATTEMPT_STATUSES) + "')", name="status"),
        Index("ix_practice_attempt_user_scenario", "user_id", "scenario_slug", "created_at"),
        Index("ix_practice_attempt_status", "status"),
        # Una sola práctica viva por visitador (dos toques rápidos no crean dos conversaciones).
        Index(
            "uq_practice_attempt_active",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('starting','live')"),
            sqlite_where=text("status IN ('starting','live')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    scenario_slug: Mapped[str] = mapped_column(String(60))
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("training_scenario_version.id", ondelete="SET NULL"), default=None
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="starting")
    provider: Mapped[str] = mapped_column(String(12))
    conversation_id: Mapped[str | None] = mapped_column(String(80), unique=True, default=None)
    conversation_url: Mapped[str | None] = mapped_column(String(300), default=None)
    webhook_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, default=None)
    audio_only: Mapped[bool] = mapped_column(default=False)
    attempt_no: Mapped[int] = mapped_column(default=1)
    greeting: Mapped[str] = mapped_column(String(200), default="")
    error_code: Mapped[str | None] = mapped_column(String(40), default=None)
    end_reason: Mapped[str | None] = mapped_column(String(80), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_polled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class PracticeTurn(Base):
    __tablename__ = "practice_turn"
    __table_args__ = (CheckConstraint("role IN ('rep','doctor')", name="role"),)

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice_attempt.id", ondelete="CASCADE"), primary_key=True
    )
    idx: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    t: Mapped[float | None] = mapped_column(Float, default=None)  # segundos desde el inicio
    duration: Mapped[float | None] = mapped_column(Float, default=None)


class PracticeEvaluation(Base):
    __tablename__ = "practice_evaluation"
    __table_args__ = (
        UniqueConstraint("attempt_id", "method", name="uq_practice_evaluation_attempt_method"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice_attempt.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[str] = mapped_column(String(20))
    total: Mapped[int]
    band: Mapped[str] = mapped_column(String(20))
    approved: Mapped[bool]
    result: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
