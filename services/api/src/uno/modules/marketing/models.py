from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from uno.db import Base, JSONType, UTCDateTime
from uno.ids import uuid7


class CommercialBatch(Base):
    __tablename__ = "commercial_batch"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_line.id"), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(30))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    data: Mapped[dict] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(20), default="preview")
    version: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    committed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class MarketingActivity(Base):
    __tablename__ = "marketing_activity"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','scheduled','in_progress','completed','cancelled')", name="status"
        ),
        Index("ix_marketing_rep_start", "representative_id", "starts_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    representative_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_line.id"))
    institution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("institution.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    kind: Mapped[str] = mapped_column(String(40))
    objective: Mapped[str] = mapped_column(String(2000))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    version: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class MarketingRevision(Base):
    __tablename__ = "marketing_revision"
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketing_activity.id"), primary_key=True
    )
    version: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    snapshot: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
