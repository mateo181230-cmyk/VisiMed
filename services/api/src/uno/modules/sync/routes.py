"""``POST /v1/sync``: el único camino de escritura del visitador (doc 01 §10.5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.context import AppContext
from uno.deps import get_ctx, get_session, require_role
from uno.modules.auth.models import User
from uno.modules.sync import service

router = APIRouter(tags=["sync"])

MAX_BATCH = 100


class EventIn(BaseModel):
    event_id: uuid.UUID
    type: str = Field(min_length=3, max_length=50)
    visit_id: uuid.UUID | None = None
    device_ts: AwareDatetime
    tz: str | None = Field(default=None, max_length=64)
    app_version: str | None = Field(default=None, max_length=20)
    payload: dict[str, Any] = Field(default_factory=dict)


class SyncIn(BaseModel):
    device_id: uuid.UUID
    sent_at: AwareDatetime
    outbox_pending: int = Field(default=0, ge=0)
    events: list[EventIn] = Field(max_length=MAX_BATCH)


class EventResultOut(BaseModel):
    event_id: uuid.UUID
    status: service.Status
    reason: str | None = None


class SyncOut(BaseModel):
    server_time: datetime
    clock_skew_s: int
    results: list[EventResultOut]


@router.post("/v1/sync", response_model=SyncOut)
async def sync(
    body: SyncIn,
    user: User = Depends(require_role("rep", "admin")),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> SyncOut:
    now = clock.now()
    app_version = next((e.app_version for e in body.events if e.app_version), None)
    skew = await service.touch_device(
        session,
        user=user,
        device_id=body.device_id,
        sent_at=body.sent_at,
        outbox_pending=body.outbox_pending,
        app_version=app_version,
        now=now,
    )
    results = await service.process_batch(
        ctx.sessionmaker,
        user=user,
        device_id=body.device_id,
        events=[
            service.IncomingEvent(
                event_id=e.event_id,
                type=e.type,
                visit_id=e.visit_id,
                device_ts=e.device_ts,
                app_version=e.app_version,
                payload=e.payload,
            )
            for e in body.events
        ],
        sent_at=body.sent_at,
        now=now,
    )
    return SyncOut(
        server_time=now,
        clock_skew_s=skew,
        results=[
            EventResultOut(event_id=r.event_id, status=r.status, reason=r.reason) for r in results
        ],
    )
