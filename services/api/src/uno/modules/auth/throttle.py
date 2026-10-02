"""Reserva atómica de intentos, portable entre SQLite y PostgreSQL.

La transacción corta toma las mismas guardas en orden, cuenta e inserta antes de
liberarlas. El trabajo de Argon2 sucede después del commit. Un proceso abortado
conserva su reserva hasta que termina la ventana; nunca abre intentos adicionales.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from uno.config import Settings
from uno.errors import ApiError
from uno.modules.auth.models import AuthAttemptLock, LoginAttempt

IP_MAX_ATTEMPTS = 20
ATTEMPT_RETENTION = timedelta(days=1)


def ip_key(raw: str) -> str:
    """Una IPv6 /64 comparte cupo; IPv4 usa su dirección real del proxy de confianza."""
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        # También permite los nombres de cliente de transportes internos de pruebas.
        return raw[:64]
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


async def _lock(
    session: AsyncSession, *, purpose: str, phone: str, ip: str, now: datetime
) -> None:
    # Un upsert adquiere un bloqueo de escritura también en SQLite; FOR UPDATE no lo hace.
    dialect = session.get_bind().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    keys = [f"{purpose}:phone:{phone}"]
    if ip:
        keys.append(f"{purpose}:ip:{ip}")
    for key in sorted(keys):
        stmt = insert(AuthAttemptLock).values(key=key, touched_at=now)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[AuthAttemptLock.key], set_={"touched_at": now}
            )
        )


async def reserve(
    session: AsyncSession,
    settings: Settings,
    *,
    purpose: str,
    phone: str,
    ip: str,
    now: datetime,
) -> LoginAttempt:
    ip = ip_key(ip)
    window = timedelta(minutes=settings.login_window_minutes)
    # Limita el crecimiento por números/IP arbitrarios. Nunca borra una ventana vigente.
    cutoff = now - max(ATTEMPT_RETENTION, window)
    await session.execute(delete(AuthAttemptLock).where(AuthAttemptLock.touched_at < cutoff))
    await session.execute(delete(LoginAttempt).where(LoginAttempt.at < cutoff))
    await _lock(session, purpose=purpose, phone=phone, ip=ip, now=now)
    active = [LoginAttempt.purpose == purpose, LoginAttempt.at > now - window]
    if purpose == "login":
        active.append(LoginAttempt.success.is_(False))
    phone_filters = [*active, LoginAttempt.phone == phone]
    if purpose == "login":
        phone_filters.append(LoginAttempt.counts_for_phone.is_(True))
    by_phone = await session.scalar(
        select(func.count()).select_from(LoginAttempt).where(*phone_filters)
    )
    by_ip = 0
    if ip:
        by_ip = (
            await session.scalar(
                select(func.count()).select_from(LoginAttempt).where(*active, LoginAttempt.ip == ip)
            )
        ) or 0
    if (by_phone or 0) >= settings.login_max_failures or (by_ip or 0) >= IP_MAX_ATTEMPTS:
        # No acumula guardas para teléfonos nuevos cuando su IP ya está bloqueada.
        await session.rollback()
        raise ApiError(
            429,
            "too_many_attempts",
            "Demasiados intentos. Espera unos minutos e inténtalo de nuevo",
            {"Retry-After": str(int(window.total_seconds()))},
        )
    attempt = LoginAttempt(
        phone=phone,
        ip=ip,
        at=now,
        success=False,
        purpose=purpose,
        finished=purpose == "register",
        counts_for_phone=True,
    )
    session.add(attempt)
    await session.commit()
    return attempt


async def finish_login(
    session: AsyncSession, attempt: LoginAttempt, *, success: bool, now: datetime
) -> None:
    await _lock(session, purpose="login", phone=attempt.phone, ip=attempt.ip, now=now)
    if success:
        # El éxito limpia fallos ya terminados; conserva los otros intentos aún en curso.
        # No se compara contra timestamps: varios eventos pueden tener la misma hora.
        await session.execute(
            update(LoginAttempt)
            .where(
                LoginAttempt.purpose == "login",
                LoginAttempt.phone == attempt.phone,
                LoginAttempt.finished.is_(True),
                LoginAttempt.success.is_(False),
                LoginAttempt.counts_for_phone.is_(True),
            )
            .values(counts_for_phone=False)
        )
    attempt.success = success
    attempt.finished = True
