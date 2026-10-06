"""Catálogo: líneas, productos, instituciones, médicos y panel (doc 01 §14; doc 03 §4.2).

La línea de producto es una dimensión de primer nivel (cambio C2 del doc 03): la unidad de
aprendizaje será médico × línea.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from uno.db import Base, UTCDateTime
from uno.ids import uuid7


class ProductLine(Base):
    __tablename__ = "product_line"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # RESPI · OSTRU · GASTRU…
    name: Mapped[str] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(default=True)
    change_seq: Mapped[int] = mapped_column(default=0, index=True)


class Product(Base):
    __tablename__ = "product"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_line.id"))
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(default=True)
    change_seq: Mapped[int] = mapped_column(default=0, index=True)


class Institution(Base):
    __tablename__ = "institution"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(160))
    address: Mapped[str | None] = mapped_column(String(200), default=None)
    city: Mapped[str | None] = mapped_column(String(80), default=None)
    lat: Mapped[float | None] = mapped_column(default=None)
    lng: Mapped[float | None] = mapped_column(default=None)
    # Radio de la geocerca. 300 m: la mayoría de visitas son en hospitales urbanos grandes.
    radius_m: Mapped[int] = mapped_column(default=300)
    ref_source: Mapped[str | None] = mapped_column(String(20), default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    change_seq: Mapped[int] = mapped_column(default=0, index=True)


class Doctor(Base):
    """Su id puede nacer en el teléfono (alta rápida sin red, T3.4)."""

    __tablename__ = "doctor"
    __table_args__ = (
        CheckConstraint("review_state IN ('approved','pending_review')", name="review_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    full_name: Mapped[str] = mapped_column(String(160))
    specialty: Mapped[str | None] = mapped_column(String(80), default=None)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("institution.id"), default=None
    )
    review_state: Mapped[str] = mapped_column(String(20), default="pending_review")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    change_seq: Mapped[int] = mapped_column(default=0, index=True)


class Panel(Base):
    """Médicos asignados a cada visitador y su línea por defecto."""

    __tablename__ = "panel"
    __table_args__ = (Index("ix_panel_representative_change", "representative_id", "change_seq"),)

    representative_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctor.id"), primary_key=True)
    default_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_line.id"), default=None
    )
    change_seq: Mapped[int] = mapped_column(default=0)
