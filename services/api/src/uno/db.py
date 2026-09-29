"""Base de datos: motor asíncrono, sesión y tipos portables entre SQLite (desarrollo/pruebas) y
PostgreSQL 16 (producción).

- Todo se guarda en UTC. ``UTCDateTime`` exige fechas con zona y devuelve siempre fechas con zona.
- ``JSONType`` es JSONB en PostgreSQL y JSON en SQLite.
- ``change_seq``: contador global monótono para la bajada incremental de estado (doc 01 §10.6).
  La fila del contador se bloquea hasta terminar la transacción, así el orden de asignación es el
  orden de confirmación y el cursor de un teléfono nunca se salta cambios.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, DateTime, MetaData, TypeDecorator, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UTCDateTime(TypeDecorator):
    """Fecha y hora siempre en UTC, con zona horaria al leer (SQLite no la guarda)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Se exige una fecha con zona horaria (UTC)")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


JSONType = JSON().with_variant(JSONB(), "postgresql")


class ChangeCounter(Base):
    __tablename__ = "change_counter"

    name: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[int] = mapped_column(default=0)


async def next_change_seq(session: AsyncSession) -> int:
    """Siguiente número de cambio. Debe llamarse dentro de la misma transacción que el cambio."""
    result = await session.execute(
        text("UPDATE change_counter SET value = value + 1 WHERE name = 'global' RETURNING value")
    )
    row = result.first()
    if row is None:  # primera vez (o base recién creada)
        session.add(ChangeCounter(name="global", value=1))
        await session.flush()
        return 1
    return int(row[0])


async def current_change_seq(session: AsyncSession) -> int:
    row = (
        await session.execute(text("SELECT value FROM change_counter WHERE name = 'global'"))
    ).first()
    return int(row[0]) if row else 0


def make_engine(database_url: str) -> AsyncEngine:
    kwargs: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        _ensure_sqlite_dir(database_url)
        kwargs["connect_args"] = {"timeout": 30}
        kwargs["poolclass"] = NullPool
    else:
        kwargs["pool_pre_ping"] = True
    engine = create_async_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def _pragmas(dbapi_conn: Any, _record: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def _ensure_sqlite_dir(database_url: str) -> None:
    path = database_url.split("///", 1)[-1]
    if path and path != ":memory:":
        parent = Path(path).resolve().parent
        os.makedirs(parent, exist_ok=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session
