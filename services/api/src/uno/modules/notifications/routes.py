"""Rutas de notificaciones (ajustes del usuario). Requieren conexión por naturaleza (ADR-20)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.context import AppContext
from uno.deps import get_ctx, get_current_user, get_session
from uno.errors import ApiError
from uno.ids import uuid7
from uno.modules.auth.models import User
from uno.modules.notifications import service
from uno.modules.notifications.models import REMIND_OPTIONS
from uno.modules.notifications.reminders import Notice, deliver

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


class PreferencesOut(BaseModel):
    push_enabled: bool
    email_enabled: bool
    email: str | None
    email_verified: bool
    pending_email: str | None
    remind_before_min: int
    remind_options: list[int]
    digest_enabled: bool
    digest_time: str
    push_subscriptions: int
    push_available: bool  # el servidor tiene llaves VAPID: se puede suscribir este dispositivo
    vapid_public_key: str | None


class PreferencesIn(BaseModel):
    push_enabled: bool | None = None
    email_enabled: bool | None = None
    remind_before_min: int | None = None
    digest_enabled: bool | None = None
    digest_time: str | None = Field(default=None, max_length=5)


async def _prefs_out(session: AsyncSession, ctx: AppContext, user: User) -> PreferencesOut:
    now = clock.now()
    prefs = await service.get_prefs(session, user.id, now)
    await session.commit()
    subs = await service.active_subscriptions(session, user.id)
    pending = await service.pending_email(session, user.id, now)
    return PreferencesOut(
        push_enabled=prefs.push_enabled,
        email_enabled=prefs.email_enabled,
        email=prefs.email,
        email_verified=prefs.email_verified_at is not None,
        pending_email=pending,
        remind_before_min=prefs.remind_before_min,
        remind_options=list(REMIND_OPTIONS),
        digest_enabled=prefs.digest_enabled,
        digest_time=prefs.digest_time,
        push_subscriptions=len(subs),
        push_available=bool(ctx.settings.vapid_public_key),
        vapid_public_key=ctx.settings.vapid_public_key or None,
    )


@router.get("/preferences", response_model=PreferencesOut)
async def get_preferences(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PreferencesOut:
    return await _prefs_out(session, ctx, user)


@router.put("/preferences", response_model=PreferencesOut)
async def put_preferences(
    body: PreferencesIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PreferencesOut:
    await service.update_prefs(session, user.id, clock.now(), **body.model_dump(exclude_unset=True))
    return await _prefs_out(session, ctx, user)


# ------------------------------------------------------------------ Web Push


class PushKeys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(max_length=2048)
    keys: PushKeys


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(max_length=2048)


@router.post("/push/subscriptions", response_model=PreferencesOut, status_code=201)
async def subscribe_push(
    body: PushSubscriptionIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PreferencesOut:
    await service.add_subscription(
        session,
        ctx.settings,
        user.id,
        clock.now(),
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        user_agent=request.headers.get("user-agent"),
    )
    return await _prefs_out(session, ctx, user)


@router.post("/push/unsubscribe", response_model=PreferencesOut)
async def unsubscribe_push(
    body: PushUnsubscribeIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PreferencesOut:
    await service.remove_subscription(session, user.id, clock.now(), endpoint=body.endpoint)
    return await _prefs_out(session, ctx, user)


# ------------------------------------------------------------------ correo


class EmailIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)


class EmailStartOut(BaseModel):
    email: str
    expires_in_min: int


class EmailVerifyIn(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


@router.post("/email", response_model=EmailStartOut, status_code=202)
async def register_email(
    body: EmailIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> EmailStartOut:
    email, minutes = await service.start_email_verification(
        session, ctx.email_sender, user.id, clock.now(), email=body.email
    )
    return EmailStartOut(email=email, expires_in_min=minutes)


@router.post("/email/verify", response_model=PreferencesOut)
async def verify_email(
    body: EmailVerifyIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PreferencesOut:
    await service.verify_email(session, user.id, clock.now(), code=body.code)
    return await _prefs_out(session, ctx, user)


@router.delete("/email", response_model=PreferencesOut)
async def remove_email(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PreferencesOut:
    now = clock.now()
    prefs = await service.get_prefs(session, user.id, now)
    prefs.email = None
    prefs.email_verified_at = None
    prefs.email_enabled = False
    prefs.updated_at = now
    await session.commit()
    return await _prefs_out(session, ctx, user)


# ------------------------------------------------------------------ prueba


class TestIn(BaseModel):
    __test__ = False  # no es una clase de pruebas para pytest
    channel: Literal["push", "email", "all"] = "all"


class TestOut(BaseModel):
    __test__ = False
    results: dict[str, str]


@router.post("/test", response_model=TestOut)
async def send_test(
    body: TestIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> TestOut:
    now = clock.now()
    if await service.recent_test_count(session, user.id, now) >= service.TEST_MAX_PER_HOUR:
        raise ApiError(429, "too_many_tests", "Ya enviaste varias pruebas. Intenta más tarde")
    await service.get_prefs(session, user.id, now)
    await session.commit()
    channels = ("push", "email") if body.channel == "all" else (body.channel,)
    notice = Notice(
        kind="test",
        ref=str(uuid7()),
        title="Prueba de UNO Visitas",
        body="Si ves este aviso, las notificaciones funcionan.",
        url="/",
        tag="test",
    )
    results = await deliver(ctx, user.id, notice, now, channels=channels, force=True)
    return TestOut(results=results)
