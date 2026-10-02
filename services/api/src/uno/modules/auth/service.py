"""Lógica de autenticación: ingreso, refresco rotatorio, cierre de sesión y alta de usuarios."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from anyio import CapacityLimiter, to_thread
from anyio.lowlevel import RunVar
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from uno.config import Settings
from uno.errors import ApiError, unauthorized
from uno.ids import uuid7
from uno.modules.auth import throttle
from uno.modules.auth.models import RefreshToken, User
from uno.security import (
    AccessToken,
    create_access_token,
    dummy_verify,
    hash_pin,
    is_valid_phone,
    is_valid_pin,
    new_refresh_token,
    normalize_phone,
    sha256_hex,
    verify_pin,
)

REFRESH_REUSE_GRACE = timedelta(seconds=10)  # tolerancia a dos refrescos casi simultáneos
_PIN_LIMITER = RunVar[CapacityLimiter]("auth_pin_limiter")


async def _pin_work[T](fn: Callable[..., T], *args: object) -> T:
    # 4 × 64 MiB por proceso con los parámetros de producción, fuera del event loop.
    try:
        limiter = _PIN_LIMITER.get()
    except LookupError:
        limiter = CapacityLimiter(4)
        _PIN_LIMITER.set(limiter)
    return await to_thread.run_sync(fn, *args, limiter=limiter)


def valid_phone(raw: str) -> str:
    phone = normalize_phone(raw)
    if not phone.isascii() or not is_valid_phone(phone):
        raise ApiError(422, "invalid_phone", "El celular debe ir en formato +573001234567")
    return phone


def _validate_pin(pin: str) -> None:
    if len(pin) != 6 or not pin.isascii() or not is_valid_pin(pin):
        raise ApiError(422, "invalid_pin", "El PIN debe tener 6 dígitos")


@dataclass(frozen=True)
class Session:
    user: User
    access: AccessToken
    refresh_token: str


async def create_user(
    session: AsyncSession,
    settings: Settings,
    *,
    full_name: str,
    phone: str,
    pin: str,
    role: str,
    now: datetime,
    timezone: str | None = None,
) -> User:
    phone = valid_phone(phone)
    _validate_pin(pin)
    full_name = full_name.strip()
    if not 2 <= len(full_name) <= 120:
        raise ApiError(422, "invalid_name", "El nombre debe tener entre 2 y 120 caracteres")
    user = User(
        id=uuid7(),
        full_name=full_name,
        phone_e164=phone,
        pin_hash=await _pin_work(hash_pin, settings, pin),
        role=role,
        timezone=timezone or settings.default_timezone,
        created_at=now,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise ApiError(409, "phone_taken", "Ya existe un usuario con ese celular") from None
    return user


async def login(
    session: AsyncSession,
    settings: Settings,
    *,
    phone: str,
    pin: str,
    ip: str,
    user_agent: str | None,
    now: datetime,
) -> Session:
    phone = valid_phone(phone)
    _validate_pin(pin)
    attempt = await throttle.reserve(
        session, settings, purpose="login", phone=phone, ip=ip, now=now
    )

    user = (
        await session.execute(select(User).where(User.phone_e164 == phone))
    ).scalar_one_or_none()
    ok = False
    if user is not None and user.is_active:
        ok = await _pin_work(verify_pin, settings, user.pin_hash, pin)
    else:
        await _pin_work(dummy_verify, settings, pin)

    await throttle.finish_login(session, attempt, success=ok, now=now)
    if not ok or user is None:
        await session.commit()
        raise unauthorized("Celular o PIN incorrectos")
    tokens = await _issue_tokens(
        session, settings, user, family_id=uuid7(), user_agent=user_agent, now=now
    )
    await session.commit()
    return tokens


async def _issue_tokens(
    session: AsyncSession,
    settings: Settings,
    user: User,
    *,
    family_id: uuid.UUID,
    user_agent: str | None,
    now: datetime,
    replaces: RefreshToken | None = None,
) -> Session:
    raw, digest = new_refresh_token()
    row = RefreshToken(
        id=uuid7(),
        user_id=user.id,
        family_id=family_id,
        token_hash=digest,
        created_at=now,
        expires_at=now + timedelta(days=settings.refresh_token_days),
        user_agent=(user_agent or "")[:300] or None,
    )
    session.add(row)
    if replaces is not None:
        replaces.revoked_at = now
        replaces.replaced_by = row.id
    access = create_access_token(settings, user_id=str(user.id), role=user.role, now=now)
    return Session(user=user, access=access, refresh_token=raw)


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def refresh(
    session: AsyncSession,
    settings: Settings,
    *,
    raw_token: str | None,
    user_agent: str | None,
    now: datetime,
) -> Session:
    if not raw_token:
        raise unauthorized()
    row = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw_token))
        )
    ).scalar_one_or_none()
    if row is None:
        raise unauthorized()

    if row.revoked_at is not None:
        within_grace = row.replaced_by is not None and now - row.revoked_at <= REFRESH_REUSE_GRACE
        if not within_grace:
            # Un token ya rotado se volvió a usar: posible robo. Se revoca toda la familia.
            await _revoke_family(session, row.family_id, now)
            await session.commit()
            raise unauthorized()
        # Refresco casi simultáneo del mismo cliente: se emite otro token sin castigar.
        user = await session.get(User, row.user_id)
        if user is None or not user.is_active:
            raise unauthorized()
        tokens = await _issue_tokens(
            session, settings, user, family_id=row.family_id, user_agent=user_agent, now=now
        )
        await session.commit()
        return tokens

    if row.expires_at <= now:
        raise unauthorized()
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    tokens = await _issue_tokens(
        session,
        settings,
        user,
        family_id=row.family_id,
        user_agent=user_agent,
        now=now,
        replaces=row,
    )
    await session.commit()
    return tokens


async def logout(session: AsyncSession, *, raw_token: str | None, now: datetime) -> None:
    if not raw_token:
        return
    row = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw_token))
        )
    ).scalar_one_or_none()
    if row is not None:
        await _revoke_family(session, row.family_id, now)
        await session.commit()
