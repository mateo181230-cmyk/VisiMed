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
from uno.errors import ApiError
from uno.modules.auth import service, throttle
from uno.modules.auth.models import User
from uno.modules.auth.permissions import capabilities
from uno.modules.notifications import service as notifications
from uno.security import constant_time_equals

router = APIRouter(tags=["auth"])

REFRESH_PATH = "/v1/auth"


class LoginIn(BaseModel):
    phone: str = Field(min_length=8, max_length=25)
    pin: str = Field(min_length=6, max_length=6)


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=25)
    email: str = Field(min_length=5, max_length=254)
    pin: str = Field(min_length=6, max_length=6)
    invite_code: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: uuid.UUID
    full_name: str
    role: str
    phone: str
    timezone: str
    management_profile: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    demo_mode: bool = False

    @classmethod
    def of(cls, user: User) -> UserOut:
        return cls(
            id=user.id,
            full_name=user.full_name,
            role=user.role,
            phone=user.phone_e164,
            timezone=user.timezone,
            management_profile=user.management_profile,
            capabilities=capabilities(user),
            demo_mode=bool((user.pilot_scope or {}).get('demo_mode')),
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


@router.post("/v1/auth/register", response_model=SessionOut, status_code=201)
async def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> SessionOut:
    code = ctx.settings.pilot_invite_code
    await throttle.reserve(
        session,
        ctx.settings,
        purpose="register",
        phone=service.valid_phone(body.phone),
        ip=_client_ip(request),
        now=clock.now(),
    )
    if not code or not constant_time_equals(body.invite_code, code):
        raise ApiError(403, "invalid_invite", "El código de invitación no es válido")
    email = notifications.normalize_email(body.email)
    name = body.full_name.strip()
    if len(name) < 2:
        raise ApiError(422, "invalid_name", "Escribe tu nombre")
    user = await service.create_user(
        session,
        ctx.settings,
        full_name=name,
        phone=body.phone,
        pin=body.pin,
        role="rep",
        now=clock.now(),
    )
    prefs = await notifications.get_prefs(session, user.id, clock.now())
    prefs.email = email
    prefs.email_enabled = False
    prefs.email_verified_at = None
    await session.commit()
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
