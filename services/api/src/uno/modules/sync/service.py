"""Sincronización idempotente (doc 01 §10.5; doc 02 T1.4).

Para cada evento, en este orden:

1. Se guarda **crudo** en ``sync_event`` (su ``event_id`` es único). Si ya existía y quedó
   ``applied`` o ``rejected`` se devuelve ese resultado; si quedó ``received`` (el servidor cayó a
   mitad de camino) se intenta aplicar de nuevo.
2. Se aplica con el manejador de su tipo, en **una transacción por evento**. El cambio de estado,
   el evento de dominio y la marca ``applied`` se confirman juntos o no se confirman.
3. Un evento inválido se marca ``rejected`` con su motivo y **no detiene el lote**.

Los eventos se aplican en orden de ``device_ts`` (estable), de modo que un lote desordenado da el
mismo estado final.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uno.modules.agenda import handlers as _agenda_handlers  # noqa: F401  (registra manejadores)
from uno.modules.auth.models import Device, User
from uno.modules.calls import handlers as _call_handlers  # noqa: F401  (registra manejadores)
from uno.modules.sync.models import SyncEvent
from uno.modules.sync.registry import EventContext, Rejected, get_handler

log = logging.getLogger("uno.sync")

Status = Literal["applied", "duplicate", "rejected"]


@dataclass(frozen=True)
class IncomingEvent:
    event_id: uuid.UUID
    type: str
    visit_id: uuid.UUID | None
    device_ts: datetime
    app_version: str | None
    payload: dict


@dataclass(frozen=True)
class EventResult:
    event_id: uuid.UUID
    status: Status
    reason: str | None = None


async def touch_device(
    session: AsyncSession,
    *,
    user: User,
    device_id: uuid.UUID,
    sent_at: datetime,
    outbox_pending: int,
    app_version: str | None,
    now: datetime,
) -> int:
    """Registra el dispositivo y devuelve el desfase de su reloj en segundos."""
    skew = int((sent_at - now).total_seconds())
    device = await session.get(Device, device_id)
    if device is None:
        device = Device(id=device_id, user_id=user.id, created_at=now)
        session.add(device)
    device.user_id = user.id
    device.last_sync_at = now
    device.outbox_pending = max(0, outbox_pending)
    device.app_version = app_version
    device.clock_skew_s = skew
    await session.commit()
    return skew


async def process_batch(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    user: User,
    device_id: uuid.UUID,
    events: list[IncomingEvent],
    sent_at: datetime,
    now: datetime,
) -> list[EventResult]:
    ordered = sorted(events, key=lambda e: e.device_ts)  # sorted es estable
    results: dict[uuid.UUID, EventResult] = {}
    for ev in ordered:
        results[ev.event_id] = await _process_event(
            sessionmaker, user=user, device_id=device_id, ev=ev, sent_at=sent_at, now=now
        )
    # La respuesta conserva el orden original del lote.
    return [results[e.event_id] for e in events]


async def _process_event(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    user: User,
    device_id: uuid.UUID,
    ev: IncomingEvent,
    sent_at: datetime,
    now: datetime,
) -> EventResult:
    # ---- 1) guardar crudo (idempotencia por event_id)
    async with sessionmaker() as session:
        session.add(
            SyncEvent(
                event_id=ev.event_id,
                device_id=device_id,
                user_id=user.id,
                visit_id=ev.visit_id,
                type=ev.type,
                device_ts=ev.device_ts,
                sent_at=sent_at,
                received_at=now,
                payload=ev.payload,
                app_version=ev.app_version,
                status="received",
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = await session.get(SyncEvent, ev.event_id)
            if existing is None or existing.user_id != user.id:
                return EventResult(ev.event_id, "rejected", "event_id_conflict")
            if existing.status == "applied":
                return EventResult(ev.event_id, "duplicate")
            if existing.status == "rejected":
                return EventResult(ev.event_id, "rejected", existing.reason)
            # status == "received": quedó a medias; se vuelve a intentar aplicar.

    # ---- 2) aplicar
    registration = get_handler(ev.type)
    if registration is None:
        return await _mark_rejected(sessionmaker, ev.event_id, "unknown_event_type")

    async with sessionmaker() as session:
        try:
            payload = registration.payload_model.model_validate(ev.payload)
            await registration.fn(
                EventContext(
                    session=session,
                    user=user,
                    event_id=ev.event_id,
                    visit_id=ev.visit_id,
                    device_id=device_id,
                    occurred_at=ev.device_ts,
                    now=now,
                ),
                payload,
            )
            await session.execute(
                update(SyncEvent)
                .where(SyncEvent.event_id == ev.event_id)
                .values(status="applied", reason=None)
            )
            await session.commit()
            return EventResult(ev.event_id, "applied")
        except Rejected as exc:
            await session.rollback()
            return await _mark_rejected(sessionmaker, ev.event_id, exc.reason)
        except ValidationError:
            await session.rollback()
            return await _mark_rejected(sessionmaker, ev.event_id, "invalid_payload")
        except IntegrityError:
            # Carrera legítima: el teléfono reenvió el evento mientras el primer intento aún se
            # aplicaba, y los dos intentaron crear lo mismo. Si el otro ya lo dejó aplicado, este
            # es un duplicado (la base impidió el doble efecto); otra violación sí es un error.
            await session.rollback()
            current = await session.get(SyncEvent, ev.event_id, populate_existing=True)
            if current is not None and current.status == "applied":
                return EventResult(ev.event_id, "duplicate")
            log.exception("violación de integridad al aplicar", extra={"event_type": ev.type})
            raise
        except Exception:
            await session.rollback()
            log.exception("error aplicando evento", extra={"event_type": ev.type})
            raise


async def _mark_rejected(
    sessionmaker: async_sessionmaker[AsyncSession], event_id: uuid.UUID, reason: str
) -> EventResult:
    async with sessionmaker() as session:
        await session.execute(
            update(SyncEvent)
            .where(SyncEvent.event_id == event_id)
            .values(status="rejected", reason=reason[:80])
        )
        await session.commit()
    return EventResult(event_id, "rejected", reason)
