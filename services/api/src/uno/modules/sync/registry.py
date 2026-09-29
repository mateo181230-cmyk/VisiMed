"""Registro de manejadores de eventos del teléfono.

Cada módulo registra los tipos de evento que sabe aplicar. El módulo de sincronización solo
conoce este registro: agregar un evento nuevo (por ejemplo ``visit_arrived``) no toca el
protocolo (doc 01 §10.2, §10.5).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from uno.modules.auth.models import User


class Rejected(Exception):
    """El evento es inválido para el estado actual: no se reintenta, se informa al teléfono."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class EventContext:
    session: AsyncSession
    user: User
    event_id: uuid.UUID
    visit_id: uuid.UUID | None
    device_id: uuid.UUID | None
    occurred_at: datetime  # hora del toque en el teléfono (device_ts)
    now: datetime  # hora del servidor


Handler = Callable[[EventContext, Any], Awaitable[None]]


@dataclass(frozen=True)
class Registration:
    event_type: str
    payload_model: type[BaseModel]
    fn: Handler


_REGISTRY: dict[str, Registration] = {}


def handles(event_type: str, payload_model: type[BaseModel]) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        if event_type in _REGISTRY:
            raise RuntimeError(f"manejador duplicado para {event_type}")
        _REGISTRY[event_type] = Registration(event_type, payload_model, fn)
        return fn

    return decorator


def get_handler(event_type: str) -> Registration | None:
    return _REGISTRY.get(event_type)


def registered_types() -> list[str]:
    return sorted(_REGISTRY)
