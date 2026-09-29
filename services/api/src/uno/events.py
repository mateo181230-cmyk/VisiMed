"""Bitácora de eventos de dominio: append-only, con doble marca de tiempo (doc 03 §5; T11.1).

- ``occurred_at``: cuándo ocurrió el hecho. ``recorded_at``: cuándo lo supo el sistema.
- Se emite en la **misma transacción** que el cambio de estado (sin escritura doble).
- El ``payload`` no puede llevar nombres, coordenadas, teléfonos, correos ni transcripciones.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Index, String, Uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from uno.db import Base, JSONType, UTCDateTime
from uno.ids import uuid7

# Claves prohibidas en cualquier nivel del payload o de las entidades (datos personales).
FORBIDDEN_KEYS = frozenset(
    {
        "name",
        "full_name",
        "doctor_name",
        "phone",
        "phone_e164",
        "email",
        "lat",
        "lng",
        "latitude",
        "longitude",
        "transcript",
        "transcription",
        "pin",
        "password",
        "token",
    }
)


class DomainEvent(Base):
    __tablename__ = "domain_event"
    __table_args__ = (Index("ix_domain_event_type_occurred", "event_type", "occurred_at"),)

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    event_type: Mapped[str] = mapped_column(String(60))
    schema_version: Mapped[int] = mapped_column(default=1)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    entities: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None, index=True)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    source: Mapped[str] = mapped_column(String(20), default="api")
    dedup_key: Mapped[str | None] = mapped_column(String(120), unique=True, default=None)


class ForbiddenPayloadError(ValueError):
    pass


def _check_keys(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ForbiddenPayloadError(f"clave prohibida en el evento: {path}{key}")
            _check_keys(inner, f"{path}{key}.")
    elif isinstance(value, list):
        for item in value:
            _check_keys(item, path)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


async def emit(
    session: AsyncSession,
    *,
    event_type: str,
    occurred_at: datetime,
    recorded_at: datetime,
    actor_type: str,
    actor_id: uuid.UUID | None,
    entities: dict[str, Any],
    payload: dict[str, Any] | None = None,
    correlation_id: uuid.UUID | None = None,
    causation_id: uuid.UUID | None = None,
    source: str = "api",
    dedup_key: str | None = None,
) -> DomainEvent:
    payload = payload or {}
    _check_keys(payload)
    _check_keys(entities)
    event = DomainEvent(
        event_id=uuid7(),
        event_type=event_type,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        actor_type=actor_type,
        actor_id=actor_id,
        entities=_jsonable(entities),
        payload=_jsonable(payload),
        correlation_id=correlation_id,
        causation_id=causation_id,
        source=source,
        dedup_key=dedup_key,
    )
    session.add(event)
    return event
