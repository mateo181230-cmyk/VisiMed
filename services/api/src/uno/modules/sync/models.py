"""Evento de sincronización: transporte del teléfono, append-only (doc 01 §10.5, §14)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from uno.db import Base, JSONType, UTCDateTime


class SyncEvent(Base):
    """El evento crudo se guarda **antes** de aplicarse; ``event_id`` único da la idempotencia."""

    __tablename__ = "sync_event"
    __table_args__ = (
        CheckConstraint("status IN ('received','applied','rejected')", name="status"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    visit_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None, index=True)
    type: Mapped[str] = mapped_column(String(50))
    device_ts: Mapped[datetime] = mapped_column(UTCDateTime)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    app_version: Mapped[str | None] = mapped_column(String(20), default=None)
    status: Mapped[str] = mapped_column(String(20), default="received")
    reason: Mapped[str | None] = mapped_column(String(80), default=None)
