"""Reloj inyectable. Todo el código de negocio pide la hora aquí; las pruebas la fijan."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_override: Callable[[], datetime] | None = None


def now() -> datetime:
    """Hora actual, siempre con zona horaria UTC."""
    if _override is not None:
        return _override()
    return datetime.now(UTC)


def set_clock(fn: Callable[[], datetime] | None) -> None:
    """Solo pruebas: fija (o restablece con ``None``) el reloj."""
    global _override
    _override = fn


def tz(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def local_date(when: datetime, tz_name: str) -> date:
    return when.astimezone(tz(tz_name)).date()


def local_day_bounds(day: date, tz_name: str) -> tuple[datetime, datetime]:
    """Inicio (incluido) y fin (excluido) de un día local, expresados en UTC."""
    zone = tz(tz_name)
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)
