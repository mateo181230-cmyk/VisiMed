from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from uno.db import Base, JSONType, UTCDateTime
from uno.ids import uuid7


class PanelContact(Base):
    """An imported contact is a doctor at a site, never a duplicate person."""

    __tablename__ = "panel_contact"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    representative_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctor.id"), index=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("institution.id"), index=True)
    source_key: Mapped[str] = mapped_column(String(120), unique=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    active: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ReceptionAvailability(Base):
    """Receiving hours can be confirmed without inventing a medical potential."""

    __tablename__ = "reception_availability"
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctor.id"), primary_key=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("institution.id"), primary_key=True
    )
    version: Mapped[int] = mapped_column(default=1)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType)
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class LocationVerification(Base):
    __tablename__ = "territory_location"
    institution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("institution.id"), primary_key=True
    )
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(20), default="verified")
    source: Mapped[str] = mapped_column(String(30))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class MedicalPotential(Base):
    __tablename__ = "medical_potential"
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctor.id"), primary_key=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("institution.id"), primary_key=True
    )
    version: Mapped[int] = mapped_column(default=1)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType)
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Pharmacy(Base):
    __tablename__ = "pharmacy"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    institution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("institution.id"), unique=True)
    representative_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    chain: Mapped[str] = mapped_column(String(160), default="Independiente")
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    active: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PharmacyVisit(Base):
    __tablename__ = "pharmacy_visit"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled','in_progress','finished','confirmed','not_done')", name="status"
        ),
        Index("ix_pharmacy_visit_rep_day", "representative_id", "scheduled_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    pharmacy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy.id"))
    representative_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    planned_by: Mapped[str] = mapped_column(String(20), default="rep")
    version: Mapped[int] = mapped_column(default=1)
    arrived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    location: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    report: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PharmacyReferral(Base):
    __tablename__ = "pharmacy_referral"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visit.id"), index=True)
    pharmacy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy.id"))
    representative_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    products: Mapped[list[str]] = mapped_column(JSONType, default=list)
    note: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class VisitRequirement(Base):
    __tablename__ = "visit_requirement"
    __table_args__ = (
        CheckConstraint(
            "(doctor_id IS NOT NULL AND pharmacy_id IS NULL) OR "
            "(doctor_id IS NULL AND pharmacy_id IS NOT NULL)",
            name="one_target",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    representative_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("doctor.id"), default=None)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("institution.id"), default=None
    )
    pharmacy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pharmacy.id"), default=None)
    cycle_start: Mapped[date] = mapped_column(Date)
    cycle_end: Mapped[date] = mapped_column(Date)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType)
    version: Mapped[int] = mapped_column(default=1)
    active: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class RoutePolicy(Base):
    __tablename__ = "route_policy"
    representative_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id"), primary_key=True
    )
    version: Mapped[int] = mapped_column(default=1)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType)
    active: Mapped[bool] = mapped_column(default=False)
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class RoutePlan(Base):
    __tablename__ = "route_plan"
    __table_args__ = (
        UniqueConstraint("representative_id", "day", "version", name="uq_route_plan_version"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    representative_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    input_hash: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[int] = mapped_column()
    max_contacts: Mapped[int] = mapped_column(default=12)
    stops: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    approval: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class RouteJob(Base):
    __tablename__ = "route_job"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(160), unique=True)
    representative_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    max_contacts: Mapped[int] = mapped_column(default=12)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    next_attempt: Mapped[datetime] = mapped_column(UTCDateTime)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("route_plan.id"), default=None)
    error: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TerritoryCommand(Base):
    __tablename__ = "territory_command"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class MapCache(Base):
    __tablename__ = "territory_map_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict[str, Any]] = mapped_column(JSONType)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
