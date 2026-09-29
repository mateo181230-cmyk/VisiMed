"""Lógica de autenticación: ingreso, refresco rotatorio, cierre de sesión y alta de usuarios."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from uno.config import Settings
from uno.errors import ApiError, unauthorized
from uno.ids import uuid7
from uno.modules.auth.models import LoginAttempt, RefreshToken, User
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

IP_MAX_FAILURES = 20
REFRESH_REUSE_GRACE = timedelta(seconds=10)  # tolerancia a dos refrescos casi simultáneos


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
    phone = normalize_phone(phone)
    if not is_valid_phone(phone):
        raise ApiError(422, "invalid_phone", "El celular debe ir en formato +573001234567")
    if not is_valid_pin(pin):
        raise ApiError(422, "invalid_pin", "El PIN debe tener 6 dígitos")
    user = User(
        id=uuid7(),
        full_name=full_name.strip(),
        phone_e164=phone,
        pin_hash=hash_pin(settings, pin),
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


async def _recent_failures(
    session: AsyncSession, *, phone: str, ip: str, window_start: datetime
) -> tuple[int, int]:
    """Fallos desde el último ingreso exitoso (o el inicio de la ventana) por celular y por IP."""
    last_ok = (
        await session.execute(
            select(func.max(LoginAttempt.at)).where(
                LoginAttempt.phone == phone, LoginAttempt.success.is_(True)
            )
        )
    ).scalar()
    since = max(window_start, last_ok) if last_ok else window_start
    by_phone = (
        await session.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.phone == phone,
                LoginAttempt.success.is_(False),
                LoginAttempt.at > since,
            )
        )
    ).scalar_one()
    by_ip = 0
    if ip:
        by_ip = (
            await session.execute(
                select(func.count())
                .select_from(LoginAttempt)
                .where(
                    LoginAttempt.ip == ip,
                    LoginAttempt.success.is_(False),
                    LoginAttempt.at > window_start,
                )
            )
        ).scalar_one()
    return int(by_phone), int(by_ip)


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
    phone = normalize_phone(phone)
    window = timedelta(minutes=settings.login_window_minutes)
    by_phone, by_ip = await _recent_failures(session, phone=phone, ip=ip, window_start=now - window)
    if by_phone >= settings.login_max_failures or by_ip >= IP_MAX_FAILURES:
        raise ApiError(
            429,
            "too_many_attempts",
            "Demasiados intentos. Espera unos minutos e inténtalo de nuevo",
            {"Retry-After": str(int(window.total_seconds()))},
        )

    user = (
        await session.execute(select(User).where(User.phone_e164 == phone))
    ).scalar_one_or_none()
    ok = False
    if user is not None and user.is_active:
        ok = verify_pin(settings, user.pin_hash, pin)
    else:
        dummy_verify(settings, pin)

    session.add(LoginAttempt(phone=phone, ip=ip, at=now, success=ok))
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
