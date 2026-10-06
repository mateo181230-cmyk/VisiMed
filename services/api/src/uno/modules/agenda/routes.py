"""Ruta de estado del visitador: ``GET /v1/me/state`` (doc 01 §10.6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.context import AppContext
from uno.deps import get_ctx, get_session, require_role
from uno.modules.agenda.state import StateOut, build_state
from uno.modules.auth.models import User

router = APIRouter(tags=["agenda"])


@router.get("/v1/me/state", response_model=StateOut)
async def my_state(
    cursor: int | None = Query(default=None, ge=0),
    user: User = Depends(require_role("rep", "admin")),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> StateOut:
    return await build_state(
        session,
        user,
        cursor,
        clock.now(),
        calls_enabled=ctx.voice_provider is not None,
        call_delay_seconds=max(30, ctx.settings.call_batch_wait_seconds),
        call_backend=ctx.settings.call_backend,
    )
