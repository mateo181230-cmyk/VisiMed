"""Agenda: visitas y las líneas que tratan (doc 01 §11, §14; doc 03 §4.2).

Estados de la visita (doc 01 §11). Este módulo crea y modifica ``scheduled`` y ``not_done``
(agenda) y ``in_progress`` y ``finished`` («Llegué» / «Terminé», módulo E4). Los demás estados
(``in_call``, ``processing``…) los usarán módulos posteriores.

«Llegué» y «Terminé» guardan la hora del toque (``arrived_at`` / ``finished_at``, la del teléfono)
y **una** lectura de ubicación por momento, con su estado de geocerca ya calculado (ver
``geofence.py``). Una visita ``finished`` con ``arrived_at`` nulo es la señal «Terminé sin
Llegué». Las coordenadas viven solo aquí: la bitácora de dominio no admite ``lat``/``lng``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from uno.db import Base, UTCDateTime

VISIT_STATUSES = (
    "scheduled",
    "in_progress",
    "finished",
    "not_done",
    "in_call",
    "processing",
    "ready",
    "error",
    "confirmed",
    "no_interview",
)
NOT_DONE_REASONS = ("doctor_unavailable", "cancelled_by_office", "rescheduled", "other")
PLANNED_BY = ("rep", "import", "suggestion", "spontaneous")


class Visit(Base):
    __tablename__ = "visit"
    __table_args__ = (
        CheckConstraint(
            "status IN ('" + "','".join(VISIT_STATUSES) + "')",
            name="status",
        ),
        Index("ix_visit_representative_scheduled", "representative_id", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)  # UUIDv7 nacido en el teléfono
    representative_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctor.id"))
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("institution.id"), default=None
    )
    primary_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_line.id"))
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)
    planned_by: Mapped[str] = mapped_column(String(20), default="rep")
    suggestion_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    not_done_reason: Mapped[str | None] = mapped_column(String(30), default=None)
    reschedule_count: Mapped[int] = mapped_column(default=0)
    # --- «Llegué»: hora del toque y ubicación (nulos hasta que ocurre)
    arrived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    arrival_fix_ts: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    arrival_lat: Mapped[float | None] = mapped_column(default=None)
    arrival_lng: Mapped[float | None] = mapped_column(default=None)
    arrival_precision_m: Mapped[float | None] = mapped_column(default=None)
    arrival_source: Mapped[str | None] = mapped_column(String(12), default=None)  # gps | reused
    arrival_geo_state: Mapped[str | None] = mapped_column(String(16), default=None)
    arrival_distance_m: Mapped[int | None] = mapped_column(default=None)
    # --- «Terminé»: ídem
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    finish_fix_ts: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    finish_lat: Mapped[float | None] = mapped_column(default=None)
    finish_lng: Mapped[float | None] = mapped_column(default=None)
    finish_precision_m: Mapped[float | None] = mapped_column(default=None)
    finish_source: Mapped[str | None] = mapped_column(String(12), default=None)
    finish_geo_state: Mapped[str | None] = mapped_column(String(16), default=None)
    finish_distance_m: Mapped[int | None] = mapped_column(default=None)
    device_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    change_seq: Mapped[int] = mapped_column(default=0, index=True)


class VisitLine(Base):
    """Una visita puede tratar 1–2 líneas; lo planeado y lo conversado pueden diferir."""

    __tablename__ = "visit_line"
    __table_args__ = (
        CheckConstraint("role IN ('planned','discussed')", name="role"),
        CheckConstraint("source IN ('agenda','extraction','rep_edit')", name="source"),
    )

    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visit.id", ondelete="CASCADE"), primary_key=True
    )
    line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_line.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), primary_key=True, default="planned")
    source: Mapped[str] = mapped_column(String(20), default="agenda")
