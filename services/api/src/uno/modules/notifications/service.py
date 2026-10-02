"""Preferencias, suscripciones push y verificación de correo.

Ajustes de notificaciones son la excepción documentada a «toda escritura pasa por /v1/sync»
(ADR-20): registrar una suscripción push o verificar un correo exigen conexión por naturaleza.

Correo: puede registrarlo de antemano el administrador (queda verificado) o el propio usuario
(recibe un código de 6 dígitos y lo confirma).
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uno.config import Settings
from uno.errors import ApiError
from uno.ids import uuid7
from uno.modules.notifications import messages
from uno.modules.notifications.models import (
    REMIND_OPTIONS,
    EmailVerification,
    NotificationLog,
    NotificationPreference,
    PushSubscription,
)
from uno.modules.notifications.senders import EmailError, EmailSender
from uno.security import constant_time_equals, sha256_hex

DIGEST_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
VERIFICATION_MINUTES = 15
VERIFICATION_MAX_ATTEMPTS = 5
VERIFICATION_MAX_PER_HOUR = 5
TEST_MAX_PER_HOUR = 10


async def get_prefs(
    session: AsyncSession, user_id: uuid.UUID, now: datetime
) -> NotificationPreference:
    prefs = await session.get(NotificationPreference, user_id)
    if prefs is None:
        prefs = NotificationPreference(user_id=user_id, updated_at=now)
        session.add(prefs)
        await session.flush()
    return prefs


async def active_subscriptions(session: AsyncSession, user_id: uuid.UUID) -> list[PushSubscription]:
    rows = await session.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == user_id, PushSubscription.disabled_at.is_(None)
        )
    )
    return list(rows.scalars().all())


async def pending_email(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> str | None:
    row = (
        await session.execute(
            select(EmailVerification)
            .where(
                EmailVerification.user_id == user_id,
                EmailVerification.consumed_at.is_(None),
                EmailVerification.expires_at > now,
                EmailVerification.attempts < VERIFICATION_MAX_ATTEMPTS,
            )
            .order_by(EmailVerification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row.email if row else None


# ------------------------------------------------------------------ preferencias


async def update_prefs(
    session: AsyncSession,
    user_id: uuid.UUID,
    now: datetime,
    *,
    push_enabled: bool | None = None,
    email_enabled: bool | None = None,
    remind_before_min: int | None = None,
    call_remind_before_min: int | None = None,
    digest_enabled: bool | None = None,
    digest_time: str | None = None,
) -> NotificationPreference:
    prefs = await get_prefs(session, user_id, now)
    if call_remind_before_min is not None:
        if call_remind_before_min not in REMIND_OPTIONS:
            raise ApiError(422, "invalid_reminder", "Elige un tiempo de llamada de la lista")
        prefs.call_remind_before_min = call_remind_before_min
    if remind_before_min is not None:
        if remind_before_min not in REMIND_OPTIONS:
            raise ApiError(422, "invalid_reminder", "Elige un tiempo de aviso de la lista")
        prefs.remind_before_min = remind_before_min
    if digest_time is not None:
        if not DIGEST_TIME_RE.match(digest_time):
            raise ApiError(422, "invalid_time", "La hora debe tener el formato HH:MM")
        prefs.digest_time = digest_time
    if digest_enabled is not None:
        prefs.digest_enabled = digest_enabled
    if push_enabled is not None:
        if push_enabled and not await active_subscriptions(session, user_id):
            raise ApiError(
                409, "no_push_subscription", "Activa las notificaciones en este dispositivo primero"
            )
        prefs.push_enabled = push_enabled
    if email_enabled is not None:
        if email_enabled and (not prefs.email or prefs.email_verified_at is None):
            raise ApiError(409, "email_not_verified", "Registra y verifica un correo primero")
        prefs.email_enabled = email_enabled
    prefs.updated_at = now
    await session.commit()
    return prefs


# ------------------------------------------------------------------ Web Push


def _host_allowed(endpoint: str, allowed: list[str]) -> bool:
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    return any(host == a or host.endswith("." + a) for a in allowed)


async def add_subscription(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    now: datetime,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None,
) -> PushSubscription:
    if len(endpoint) > 2048 or not _host_allowed(endpoint, settings.push_allowed_hosts):
        # Evita que un cliente use el servidor para llamar a direcciones arbitrarias (SSRF).
        raise ApiError(422, "invalid_endpoint", "Servicio de notificaciones no permitido")
    if not (10 <= len(p256dh) <= 200 and 8 <= len(auth) <= 100):
        raise ApiError(422, "invalid_keys", "Llaves de suscripción inválidas")
    had_active = bool(await active_subscriptions(session, user_id))

    sub = (
        await session.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    ).scalar_one_or_none()
    if sub is None:
        sub = PushSubscription(id=uuid7(), endpoint=endpoint, created_at=now)
        session.add(sub)
    sub.user_id = user_id
    sub.p256dh = p256dh
    sub.auth = auth
    sub.user_agent = (user_agent or "")[:300] or None
    sub.disabled_at = None
    sub.failed_count = 0

    prefs = await get_prefs(session, user_id, now)
    if not had_active:
        prefs.push_enabled = True  # el usuario acaba de conceder el permiso
        prefs.updated_at = now
    await session.commit()
    return sub


async def remove_subscription(
    session: AsyncSession, user_id: uuid.UUID, now: datetime, *, endpoint: str
) -> None:
    sub = (
        await session.execute(
            select(PushSubscription).where(
                PushSubscription.endpoint == endpoint, PushSubscription.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if sub is not None:
        await session.delete(sub)
        await session.flush()
    if not await active_subscriptions(session, user_id):
        prefs = await get_prefs(session, user_id, now)
        prefs.push_enabled = False
        prefs.updated_at = now
    await session.commit()


# ------------------------------------------------------------------ correo


def normalize_email(raw: str) -> str:
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise ApiError(422, "invalid_email", "Ese correo no es válido") from None


async def start_email_verification(
    session: AsyncSession,
    sender: EmailSender,
    user_id: uuid.UUID,
    now: datetime,
    *,
    email: str,
) -> tuple[str, int]:
    email = normalize_email(email)
    recent = (
        await session.execute(
            select(func.count())
            .select_from(EmailVerification)
            .where(
                EmailVerification.user_id == user_id,
                EmailVerification.created_at > now - timedelta(hours=1),
            )
        )
    ).scalar_one()
    if recent >= VERIFICATION_MAX_PER_HOUR:
        raise ApiError(429, "too_many_codes", "Pediste demasiados códigos. Intenta más tarde")

    # Los códigos anteriores dejan de servir.
    old = (
        (
            await session.execute(
                select(EmailVerification).where(
                    EmailVerification.user_id == user_id, EmailVerification.consumed_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    for row in old:
        row.consumed_at = now

    code = f"{secrets.randbelow(10**6):06d}"
    session.add(
        EmailVerification(
            id=uuid7(),
            user_id=user_id,
            email=email,
            code_hash=_code_hash(user_id, code),
            created_at=now,
            expires_at=now + timedelta(minutes=VERIFICATION_MINUTES),
        )
    )
    await session.flush()
    try:
        await sender.send(messages.verification_email(email, code, VERIFICATION_MINUTES))
    except EmailError:
        await session.rollback()
        raise ApiError(
            502, "email_send_failed", "No pudimos enviar el correo. Inténtalo de nuevo"
        ) from None
    await session.commit()
    return email, VERIFICATION_MINUTES


def _code_hash(user_id: uuid.UUID, code: str) -> str:
    return sha256_hex(f"{user_id}:{code}")


async def verify_email(
    session: AsyncSession, user_id: uuid.UUID, now: datetime, *, code: str
) -> NotificationPreference:
    row = (
        await session.execute(
            select(EmailVerification)
            .where(
                EmailVerification.user_id == user_id,
                EmailVerification.consumed_at.is_(None),
                EmailVerification.expires_at > now,
            )
            .order_by(EmailVerification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(422, "invalid_code", "El código venció o no existe. Pide uno nuevo")
    if row.attempts >= VERIFICATION_MAX_ATTEMPTS:
        raise ApiError(429, "too_many_attempts", "Demasiados intentos. Pide un código nuevo")
    row.attempts += 1
    if not constant_time_equals(row.code_hash, _code_hash(user_id, code.strip())):
        await session.commit()
        raise ApiError(422, "invalid_code", "El código no es correcto")
    row.consumed_at = now
    prefs = await get_prefs(session, user_id, now)
    prefs.email = row.email
    prefs.email_verified_at = now
    prefs.email_enabled = True
    prefs.updated_at = now
    await session.commit()
    return prefs


async def admin_register_email(
    session: AsyncSession, user_id: uuid.UUID, now: datetime, *, email: str
) -> NotificationPreference:
    """Correo registrado de antemano por el administrador: queda verificado."""
    prefs = await get_prefs(session, user_id, now)
    prefs.email = normalize_email(email)
    prefs.email_verified_at = now
    prefs.email_enabled = True
    prefs.updated_at = now
    await session.commit()
    return prefs


async def recent_test_count(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(NotificationLog)
                .where(
                    NotificationLog.user_id == user_id,
                    NotificationLog.kind == "test",
                    NotificationLog.created_at > now - timedelta(hours=1),
                )
            )
        ).scalar_one()
    )
