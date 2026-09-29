"""Fixtures de pruebas.

Por defecto usan SQLite (rápido). Con ``UNO_TEST_DB=postgres`` corren contra un PostgreSQL 16 real
embebido (paquete ``pgserver``), sin Docker:

    UNO_TEST_DB=postgres uv run python -m pytest
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text

from uno import clock
from uno import models as _models  # noqa: F401
from uno.config import Settings
from uno.context import AppContext
from uno.db import Base
from uno.main import create_app
from uno.modules.auth.service import create_user
from uno.modules.notifications.senders import MemoryEmailSender, MemoryPushSender
from uno.seed import seed_lines

# Las pruebas nunca leen el .env de desarrollo: solo lo que fijan ellas mismas.
Settings.model_config["env_file"] = None

BACKEND = os.environ.get("UNO_TEST_DB", "sqlite")

# 2026-09-29 12:00 UTC = 07:00 en Bogotá (UTC-5)
T0 = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)

VAPID_PUBLIC = (
    "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM"
)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def now(self) -> datetime:
        return self.t

    def advance(self, **kwargs: float) -> None:
        self.t += timedelta(**kwargs)

    def set(self, value: datetime) -> None:
        self.t = value


@dataclass
class Env:
    app: FastAPI
    ctx: AppContext
    client: httpx.AsyncClient
    push: MemoryPushSender
    email: MemoryEmailSender
    lines: dict[str, uuid.UUID]
    clock: FakeClock

    @property
    def settings(self) -> Settings:
        return self.ctx.settings


@pytest.fixture(scope="session")
def pg_url() -> AsyncIterator[str | None]:
    if BACKEND != "postgres":
        yield None
        return
    import pgserver

    data_dir = tempfile.mkdtemp(prefix="uno_pg_")
    server = pgserver.get_server(data_dir, cleanup_mode="stop")
    uri = server.get_uri()
    yield uri.replace("postgresql://", "postgresql+asyncpg://", 1)
    server.cleanup()


def _settings(tmp_path: Path, pg_url: str | None, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "env": "test",
        "database_url": pg_url or f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        "jwt_secret": "test-secret-test-secret-test-secret-1234",
        "argon2_time_cost": 1,
        "argon2_memory_cost": 8,
        "argon2_parallelism": 1,
        "push_backend": "memory",
        "email_backend": "memory",
        "vapid_public_key": VAPID_PUBLIC,
        "vapid_private_key": "unused-in-tests",
        "mail_dir": str(tmp_path / "mail"),
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@asynccontextmanager
async def _make_env(tmp_path: Path, pg_url: str | None, **overrides: object) -> AsyncIterator[Env]:
    fake = FakeClock(T0)
    clock.set_clock(fake.now)
    push = MemoryPushSender()
    email = MemoryEmailSender()
    voice_provider = overrides.pop("voice_provider", None)
    conversation_provider = overrides.pop("conversation_provider", None)
    settings = _settings(tmp_path, pg_url, **overrides)
    app = create_app(
        settings,
        push_sender=push,
        email_sender=email,
        voice_provider=voice_provider,  # type: ignore[arg-type]
        conversation_provider=conversation_provider,  # type: ignore[arg-type]
    )
    ctx: AppContext = app.state.ctx
    async with ctx.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("INSERT INTO change_counter (name, value) VALUES ('global', 0)"))
    await seed_lines(ctx)
    async with ctx.sessionmaker() as session:
        from sqlalchemy import select

        from uno.modules.catalog.models import ProductLine

        lines = {r.code: r.id for r in (await session.execute(select(ProductLine))).scalars()}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield Env(app, ctx, client, push, email, lines, fake)
        finally:
            clock.set_clock(None)
            async with ctx.engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await ctx.engine.dispose()


@pytest_asyncio.fixture
async def env(tmp_path: Path, pg_url: str | None) -> AsyncIterator[Env]:
    async with _make_env(tmp_path, pg_url) as e:
        yield e


@pytest.fixture
def make_env(tmp_path: Path, pg_url: str | None) -> Callable[..., object]:
    """Fábrica para pruebas que necesitan una configuración distinta o dos entornos."""
    counter = {"n": 0}

    def factory(**overrides: object):  # type: ignore[no-untyped-def]
        counter["n"] += 1
        sub = tmp_path / f"env{counter['n']}"
        sub.mkdir()
        return _make_env(sub, pg_url, **overrides)

    return factory


# ------------------------------------------------------------------ ayudantes


REP_PHONE = "+573001112233"
REP_PIN = "135790"
OTHER_PHONE = "+573004445566"
ADMIN_PHONE = "+573009998877"
PIN = "246810"


async def make_user(
    env: Env, *, phone: str = REP_PHONE, pin: str = PIN, role: str = "rep", name: str = "Ana Rep"
) -> uuid.UUID:
    async with env.ctx.sessionmaker() as session:
        user = await create_user(
            session,
            env.settings,
            full_name=name,
            phone=phone,
            pin=pin,
            role=role,
            now=clock.now(),
        )
        await session.commit()
        return user.id


async def login(env: Env, phone: str = REP_PHONE, pin: str = PIN) -> str:
    r = await env.client.post("/v1/auth/login", json={"phone": phone, "pin": pin})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def rep_token(env: Env, phone: str = REP_PHONE, name: str = "Ana Rep") -> str:
    await make_user(env, phone=phone, name=name)
    return await login(env, phone)
