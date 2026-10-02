"""Usuarios, sesiones y dispositivos (doc 01 §14)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Uuid, true
from sqlalchemy.orm import Mapped, mapped_column

from uno.db import Base, UTCDateTime
from uno.ids import uuid7

ROLES = ("rep", "manager", "admin")


class User(Base):
    """Un usuario del sistema. El visitador es un usuario con rol ``rep``."""

    __tablename__ = "app_user"  # ``user`` es palabra reservada en PostgreSQL
    __table_args__ = (CheckConstraint("role IN ('rep','manager','admin')", name="role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    full_name: Mapped[str] = mapped_column(String(120))
    phone_e164: Mapped[str] = mapped_column(String(20), unique=True)
    pin_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="rep")
    is_active: Mapped[bool] = mapped_column(default=True)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Bogota")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class RefreshToken(Base):
    """Token de refresco opaco y rotatorio. Reutilizar uno ya rotado revoca toda la familia."""

    __tablename__ = "refresh_token"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    user_agent: Mapped[str | None] = mapped_column(String(300), default=None)


class LoginAttempt(Base):
    """Reservas de ingreso/registro; los ingresos en curso ya consumen el límite."""

    __tablename__ = "login_attempt"
    __table_args__ = (
        Index("ix_login_attempt_phone_at", "phone", "at"),
        Index("ix_login_attempt_purpose_ip_at", "purpose", "ip", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    phone: Mapped[str] = mapped_column(String(20))
    ip: Mapped[str] = mapped_column(String(64), default="")
    at: Mapped[datetime] = mapped_column(UTCDateTime)
    success: Mapped[bool]
    purpose: Mapped[str] = mapped_column(String(12), default="login", server_default="login")
    finished: Mapped[bool] = mapped_column(default=True, server_default=true())
    counts_for_phone: Mapped[bool] = mapped_column(default=True, server_default=true())


class AuthAttemptLock(Base):
    """Guardas de transacción compartidas por procesos; nunca contienen credenciales."""

    __tablename__ = "auth_attempt_lock"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    touched_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class Device(Base):
    """Un teléfono. Su id nace en el propio teléfono."""

    __tablename__ = "device"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    platform: Mapped[str | None] = mapped_column(String(40), default=None)
    app_version: Mapped[str | None] = mapped_column(String(20), default=None)
    installed: Mapped[bool] = mapped_column(default=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    outbox_pending: Mapped[int] = mapped_column(default=0)
    clock_skew_s: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
