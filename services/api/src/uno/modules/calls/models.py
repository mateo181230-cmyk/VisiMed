"""Llamadas de resumen y fichas de visita (doc 01 §12–§14).

- ``Call``: una llamada del agente de voz al visitador. Cubre de 1 a 5 visitas (institución con
  varios médicos). Tiene su propio ciclo: ``queued`` (por marcar) → ``dialing`` (marcada, esperando
  el resultado) → ``completed`` | ``failed``; ``cancelled`` si ya no hace falta.
- ``CallVisit``: qué visitas cubre y en qué orden. Una visita solo puede estar en **una** llamada
  viva a la vez (índice único parcial): dos trabajadores no pueden llamar dos veces por lo mismo.
- ``VisitReport``: la ficha de cada visita, con los campos extraídos, su confianza y quién los
  escribió (la llamada o el visitador; lo del visitador nunca se pisa).

La transcripción y el análisis crudos se guardan aquí (contienen datos personales: nunca van a
logs ni a la bitácora de dominio).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from uno.db import Base, JSONType, UTCDateTime
from uno.ids import uuid7

CALL_STATUSES = ("queued", "dialing", "completed", "failed", "cancelled")
CALL_DIRECTIONS = ("outbound", "inbound")
LIVE_CALL_STATUSES = ("queued", "dialing")
REPORT_STATUSES = ("ready", "confirmed")


class Call(Base):
    __tablename__ = "call"
    __table_args__ = (
        CheckConstraint("status IN ('" + "','".join(CALL_STATUSES) + "')", name="status"),
        CheckConstraint("direction IN ('outbound','inbound')", name="direction"),
        Index("ix_call_status_scheduled", "status", "scheduled_for"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    representative_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    direction: Mapped[str] = mapped_column(String(10), default="outbound")
    purpose: Mapped[str] = mapped_column(String(20), default="summary")
    reminder_key: Mapped[str | None] = mapped_column(String(100), unique=True, default=None)
    status: Mapped[str] = mapped_column(String(12), default="queued")
    attempt: Mapped[int] = mapped_column(default=0)  # veces que se ha marcado
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime)
    is_closing: Mapped[bool] = mapped_column(default=False)  # llamada de cierre de la tarde
    provider: Mapped[str] = mapped_column(String(20), default="elevenlabs")
    provider_conversation_id: Mapped[str | None] = mapped_column(
        String(80), unique=True, default=None
    )
    provider_call_id: Mapped[str | None] = mapped_column(String(80), default=None)
    dialed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    duration_s: Mapped[int | None] = mapped_column(default=None)
    failure_reason: Mapped[str | None] = mapped_column(String(30), default=None)
    transcript: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType, default=None)
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)
    summary: Mapped[str | None] = mapped_column(String(2000), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class CallVisit(Base):
    __tablename__ = "call_visit"
    __table_args__ = (
        UniqueConstraint("call_id", "position", name="uq_call_visit_call_id_position"),
        # Una visita, una sola llamada viva (queued o dialing) a la vez.
        Index(
            "uq_call_visit_live",
            "visit_id",
            unique=True,
            postgresql_where=text("live"),
            sqlite_where=text("live"),
        ),
    )

    call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("call.id", ondelete="CASCADE"), primary_key=True
    )
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visit.id"), primary_key=True)
    position: Mapped[int]  # 1 = primera visita de la llamada
    live: Mapped[bool] = mapped_column(default=True)


class VisitReport(Base):
    """La ficha de una visita: lo que la llamada (y luego el visitador) dice que pasó."""

    __tablename__ = "visit_report"
    __table_args__ = (
        CheckConstraint("status IN ('ready','confirmed')", name="status"),
        Index("ix_visit_report_change", "change_seq"),
    )

    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visit.id"), primary_key=True)
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call.id", ondelete="SET NULL"), default=None
    )
    status: Mapped[str] = mapped_column(String(12), default="ready")
    # {campo: {"value": …, "confidence": "high|medium|low", "source": "call|rep_edit"}}
    fields: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    complete: Mapped[bool] = mapped_column(default=False)
    problems: Mapped[list[str]] = mapped_column(JSONType, default=list)
    extractor_version: Mapped[str] = mapped_column(String(40), default="elevenlabs-v1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    change_seq: Mapped[int] = mapped_column(default=0)
