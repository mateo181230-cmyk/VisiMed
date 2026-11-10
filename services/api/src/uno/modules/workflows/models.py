from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from uno.db import Base, JSONType, UTCDateTime
from uno.ids import uuid7


class FollowupTask(Base):
    __tablename__ = "followup_task"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    source_key: Mapped[str] = mapped_column(String(64), unique=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visit.id"), index=True)
    representative_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    owner: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(1500))
    due_on: Mapped[date | None] = mapped_column(Date, default=None)
    due_manual: Mapped[bool] = mapped_column(default=False)
    next_objective: Mapped[str | None] = mapped_column(String(1500), default=None)
    status: Mapped[str] = mapped_column(String(20), default="open")
    evidence: Mapped[str] = mapped_column(String(2000), default="")
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class RouteIncident(Base):
    __tablename__ = "route_incident"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    representative_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("route_plan.id"))
    day: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(20))
    resume_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    reason: Mapped[str] = mapped_column(String(1000))
    visit_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_document"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_line.id"), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    version: Mapped[int] = mapped_column(default=1)
    revision: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    slides: Mapped[list[dict]] = mapped_column(JSONType, default=list)
    original: Mapped[bytes] = mapped_column(LargeBinary)
    review_note: Mapped[str] = mapped_column(String(2000), default="")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"), default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class VisitLearning(Base):
    __tablename__ = "visit_learning"
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visit.id"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
