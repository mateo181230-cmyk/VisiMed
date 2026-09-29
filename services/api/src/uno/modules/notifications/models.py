"""Notificaciones: preferencias, suscripciones push, verificación de correo y bitácora de envíos."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from uno.db import Base, UTCDateTime
from uno.ids import uuid7

REMIND_OPTIONS = (0, 10, 15, 30, 45, 60, 120)  # minutos antes; 0 = sin recordatorio de visita
CHANNELS = ("push", "email")
KINDS = ("visit_reminder", "daily_digest", "test")


class NotificationPreference(Base):
    __tablename__ = "notification_preference"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    push_enabled: Mapped[bool] = mapped_column(default=False)
    email_enabled: Mapped[bool] = mapped_column(default=False)
    email: Mapped[str | None] = mapped_column(String(254), default=None)
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    remind_before_min: Mapped[int] = mapped_column(default=30)
    digest_enabled: Mapped[bool] = mapped_column(default=True)
    digest_time: Mapped[str] = mapped_column(String(5), default="07:30")  # HH:MM hora local
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PushSubscription(Base):
    """Suscripción Web Push de un navegador o PWA instalada."""

    __tablename__ = "push_subscription"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    endpoint: Mapped[str] = mapped_column(String(2048), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(String(300), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    failed_count: Mapped[int] = mapped_column(default=0)
    disabled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class EmailVerification(Base):
    """Código de 6 dígitos para confirmar un correo registrado por el propio usuario."""

    __tablename__ = "email_verification"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(254))
    code_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    attempts: Mapped[int] = mapped_column(default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class NotificationLog(Base):
    """Un envío por (usuario, tipo, referencia, canal). La restricción única evita duplicados."""

    __tablename__ = "notification_log"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "ref", "channel", name="uq_notification_once"),
        CheckConstraint("channel IN ('push','email')", name="channel"),
        CheckConstraint("status IN ('pending','sent','failed','skipped')", name="status"),
        Index("ix_notification_log_status_next", "status", "next_attempt_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    ref: Mapped[str] = mapped_column(String(80))
    channel: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    error: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
