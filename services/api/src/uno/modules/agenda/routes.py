"""Ruta de estado del visitador: ``GET /v1/me/state`` (doc 01 §10.6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.deps import get_session, require_role
from uno.modules.agenda.state import StateOut, build_state
from uno.modules.auth.models import User

router = APIRouter(tags=["agenda"])


@router.get("/v1/me/state", response_model=StateOut)
async def my_state(
    cursor: int | None = Query(default=None, ge=0),
    user: User = Depends(require_role("rep", "admin")),
    session: AsyncSession = Depends(get_session),
) -> StateOut:
    return await build_state(session, user, cursor, clock.now())
