"""Rutas de autenticación (doc 01 §15): ``/v1/auth/*`` y ``/v1/me``."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.context import AppContext
from uno.deps import get_ctx, get_current_user, get_session
from uno.modules.auth import service
from uno.modules.auth.models import User

router = APIRouter(tags=["auth"])

REFRESH_PATH = "/v1/auth"


class LoginIn(BaseModel):
    phone: str = Field(min_length=8, max_length=25)
    pin: str = Field(min_length=6, max_length=6)


class UserOut(BaseModel):
    id: uuid.UUID
    full_name: str
    role: str
    phone: str
    timezone: str

    @classmethod
    def of(cls, user: User) -> UserOut:
        return cls(
            id=user.id,
            full_name=user.full_name,
            role=user.role,
            phone=user.phone_e164,
            timezone=user.timezone,
        )


class SessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105  (tipo de esquema HTTP, no una credencial)
    expires_at: datetime
    user: UserOut


def _set_refresh_cookie(response: Response, ctx: AppContext, token: str) -> None:
    response.set_cookie(
        ctx.settings.refresh_cookie_name,
        token,
        max_age=ctx.settings.refresh_token_days * 24 * 3600,
        httponly=True,
        secure=ctx.settings.cookie_secure,
        samesite="strict",
        path=REFRESH_PATH,
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.post("/v1/auth/login", response_model=SessionOut)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> SessionOut:
    result = await service.login(
        session,
        ctx.settings,
        phone=body.phone,
        pin=body.pin,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        now=clock.now(),
    )
    _set_refresh_cookie(response, ctx, result.refresh_token)
    return SessionOut(
        access_token=result.access.token,
        expires_at=result.access.expires_at,
        user=UserOut.of(result.user),
    )


@router.post("/v1/auth/refresh", response_model=SessionOut)
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> SessionOut:
    result = await service.refresh(
        session,
        ctx.settings,
        raw_token=request.cookies.get(ctx.settings.refresh_cookie_name),
        user_agent=request.headers.get("user-agent"),
        now=clock.now(),
    )
    _set_refresh_cookie(response, ctx, result.refresh_token)
    return SessionOut(
        access_token=result.access.token,
        expires_at=result.access.expires_at,
        user=UserOut.of(result.user),
    )


@router.post("/v1/auth/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> Response:
    await service.logout(
        session,
        raw_token=request.cookies.get(ctx.settings.refresh_cookie_name),
        now=clock.now(),
    )
    response.delete_cookie(ctx.settings.refresh_cookie_name, path=REFRESH_PATH)
    response.status_code = 204
    return response


@router.get("/v1/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.of(user)
