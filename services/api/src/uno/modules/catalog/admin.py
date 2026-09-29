"""Operaciones de administración (doc 01 §15): usuarios y correo de notificaciones pre-registrado.

El administrador puede registrar de antemano el correo de un visitador: queda verificado y
recibirá los avisos sin pasar por el código de confirmación.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.context import AppContext
from uno.deps import get_ctx, get_session, require_role
from uno.errors import not_found
from uno.modules.auth import service as auth_service
from uno.modules.auth.models import ROLES, User
from uno.modules.auth.routes import UserOut
from uno.modules.notifications import service as notif_service

router = APIRouter(prefix="/v1/admin", tags=["admin"])
_admin = require_role("admin")


class UserCreateIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=25)
    pin: str = Field(min_length=6, max_length=6)
    role: str = "rep"
    email: str | None = Field(default=None, max_length=254)


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreateIn,
    _: User = Depends(_admin),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> UserOut:
    from uno.errors import ApiError

    if body.role not in ROLES:
        raise ApiError(422, "invalid_role", "Rol inválido")
    now = clock.now()
    user = await auth_service.create_user(
        session,
        ctx.settings,
        full_name=body.full_name,
        phone=body.phone,
        pin=body.pin,
        role=body.role,
        now=now,
    )
    if body.email:
        await notif_service.admin_register_email(session, user.id, now, email=body.email)
    else:
        await session.commit()
    return UserOut.of(user)


@router.get("/users", response_model=list[UserOut])
async def list_users(
    _: User = Depends(_admin), session: AsyncSession = Depends(get_session)
) -> list[UserOut]:
    rows = (await session.execute(select(User).order_by(User.full_name))).scalars().all()
    return [UserOut.of(u) for u in rows]


class EmailIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)


@router.put("/users/{user_id}/notification-email", status_code=204)
async def set_notification_email(
    user_id: uuid.UUID,
    body: EmailIn,
    _: User = Depends(_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    if await session.get(User, user_id) is None:
        raise not_found("Usuario no encontrado")
    await notif_service.admin_register_email(session, user_id, clock.now(), email=body.email)
