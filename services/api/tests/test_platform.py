"""Migraciones, bitácora, identificadores, seguridad y utilidades de la plataforma."""

from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from typer.testing import CliRunner

from uno import clock, events
from uno.db import Base
from uno.ids import uuid7
from uno.security import is_valid_phone, is_valid_pin, normalize_phone

from .conftest import BACKEND, Env

API_DIR = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ migraciones


def _alembic_cfg(url: str) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.cmd_opts = type("O", (), {"x": [f"url={url}"]})()  # type: ignore[attr-defined]
    return cfg


@pytest.fixture
def migration_url(tmp_path: Path, pg_url: str | None) -> str:
    if pg_url:
        return pg_url
    return f"sqlite+aiosqlite:///{(tmp_path / 'mig.db').as_posix()}"


async def _schema_diff(url: str) -> list:  # type: ignore[type-arg]
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:

            def run(sync_conn):  # type: ignore[no-untyped-def]
                ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
                return compare_metadata(ctx, Base.metadata)

            return await conn.run_sync(run)
    finally:
        await engine.dispose()


async def _reset(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        if url.startswith("postgresql"):
            await conn.execute(text("DROP FUNCTION IF EXISTS uno_sync_event_guard() CASCADE"))
            await conn.execute(text("DROP FUNCTION IF EXISTS uno_forbid_change() CASCADE"))
    await engine.dispose()


async def test_migrations_upgrade_match_models_and_downgrade(migration_url: str) -> None:
    """Las migraciones producen exactamente el esquema de los modelos (sin deriva) y se revierten."""
    await _reset(migration_url)
    cfg = _alembic_cfg(migration_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    assert await _schema_diff(migration_url) == []

    engine = create_async_engine(migration_url)
    async with engine.connect() as conn:
        seeded = (
            await conn.execute(text("SELECT value FROM change_counter WHERE name='global'"))
        ).scalar()
    await engine.dispose()
    assert seeded == 0

    await asyncio.to_thread(command.downgrade, cfg, "base")
    engine = create_async_engine(migration_url)
    async with engine.connect() as conn:

        def tables(sync_conn):  # type: ignore[no-untyped-def]
            from sqlalchemy import inspect

            return set(inspect(sync_conn).get_table_names()) - {"alembic_version"}

        left = await conn.run_sync(tables)
    await engine.dispose()
    assert left == set()


@pytest.mark.skipif(BACKEND != "postgres", reason="los disparadores son de PostgreSQL")
async def test_append_only_triggers_in_postgres(migration_url: str) -> None:
    from sqlalchemy.exc import DBAPIError

    await _reset(migration_url)
    await asyncio.to_thread(command.upgrade, _alembic_cfg(migration_url), "head")
    engine = create_async_engine(migration_url)
    uid, eid = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app_user (id, full_name, phone_e164, pin_hash, role, is_active, timezone, created_at) "
                "VALUES (:i, 'x', '+573000000000', 'h', 'rep', true, 'America/Bogota', now())"
            ),
            {"i": uid},
        )
        await conn.execute(
            text(
                "INSERT INTO sync_event (event_id, user_id, type, device_ts, received_at, payload, status) "
                "VALUES (:e, :u, 't', now(), now(), '{}'::jsonb, 'received')"
            ),
            {"e": eid, "u": uid},
        )
        await conn.execute(
            text(
                "INSERT INTO domain_event (event_id, event_type, schema_version, occurred_at, recorded_at, actor_type, entities, payload, source) "
                "VALUES (:e, 'x', 1, now(), now(), 'system', '{}'::jsonb, '{}'::jsonb, 'api')"
            ),
            {"e": eid},
        )
    # domain_event: ni UPDATE ni DELETE
    for stmt in ("UPDATE domain_event SET source='otro'", "DELETE FROM domain_event"):
        with pytest.raises(DBAPIError, match="append-only"):
            async with engine.begin() as conn:
                await conn.execute(text(stmt))
    # sync_event: solo status y reason pueden cambiar
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE sync_event SET status='applied', reason=NULL"))
    with pytest.raises(DBAPIError, match="inmutable"):
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE sync_event SET payload = CAST(:p AS jsonb)"), {"p": '{"a": 1}'}
            )
    with pytest.raises(DBAPIError, match="append-only"):
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM sync_event"))
    await engine.dispose()
    await _reset(migration_url)


# ------------------------------------------------------------------ bitácora de dominio


async def test_domain_event_rejects_personal_data(env: Env) -> None:
    async with env.ctx.sessionmaker() as s:
        base = dict(
            event_type="x",
            occurred_at=clock.now(),
            recorded_at=clock.now(),
            actor_type="system",
            actor_id=None,
        )
        for bad in (
            {"full_name": "Dra. Laura"},
            {"nested": {"lat": 4.6}},
            {"list": [{"Email": "a@b.co"}]},
            {"transcript": "hola"},
        ):
            with pytest.raises(events.ForbiddenPayloadError):
                await events.emit(s, entities={}, payload=bad, **base)  # type: ignore[arg-type]
        with pytest.raises(events.ForbiddenPayloadError):
            await events.emit(s, entities={"phone": "+57"}, payload={}, **base)  # type: ignore[arg-type]
        ok = await events.emit(
            s,
            entities={"doctor_id": uuid.uuid4()},
            payload={"when": clock.now(), "n": 1},
            **base,  # type: ignore[arg-type]
        )
        assert isinstance(ok.entities["doctor_id"], str)  # se guarda como JSON


# ------------------------------------------------------------------ identificadores y reloj


def test_uuid7_is_valid_and_time_ordered() -> None:
    ids = [uuid7() for _ in range(2000)]
    assert all(i.version == 7 and i.variant == uuid.RFC_4122 for i in ids)
    assert len(set(ids)) == 2000
    # Ordenables por tiempo a nivel de milisegundo.
    prefixes = [i.bytes[:6] for i in ids]
    assert prefixes == sorted(prefixes)


def test_local_day_bounds_in_bogota() -> None:
    start, end = clock.local_day_bounds(date(2026, 9, 29), "America/Bogota")
    assert start == datetime(2026, 9, 29, 5, 0, tzinfo=UTC)
    assert end == datetime(2026, 9, 30, 5, 0, tzinfo=UTC)
    # Una visita a las 23:30 hora de Colombia cae en el día correcto (T1.1 CA4).
    late = datetime(2026, 9, 30, 4, 30, tzinfo=UTC)  # 23:30 del 29
    assert start <= late < end
    assert clock.local_date(late, "America/Bogota") == date(2026, 9, 29)


def test_phone_and_pin_validation() -> None:
    assert normalize_phone("+57 (300) 111-2233") == "+573001112233"
    assert is_valid_phone("+573001112233") and not is_valid_phone("3001112233")
    assert not is_valid_phone("+57 300") and not is_valid_phone("+0123456789")
    assert is_valid_pin("012345") and not is_valid_pin("12345") and not is_valid_pin("1234567")
    assert not is_valid_pin("12345a")


def test_pin_hashing_uses_argon2id() -> None:
    from uno.config import Settings
    from uno.security import hash_pin, verify_pin

    s = Settings(argon2_time_cost=1, argon2_memory_cost=8, argon2_parallelism=1)
    h = hash_pin(s, "246810")
    assert h.startswith("$argon2id$")
    assert verify_pin(s, h, "246810") and not verify_pin(s, h, "246811")
    assert not verify_pin(s, "no-es-un-hash", "246810")


def test_production_requires_a_real_secret() -> None:
    from uno.config import Settings

    with pytest.raises(ValueError):
        Settings(env="prod", cookie_secure=True)
    with pytest.raises(ValueError):
        Settings(env="prod", jwt_secret="x" * 40, cookie_secure=False)
    Settings(env="prod", jwt_secret="x" * 40, cookie_secure=True)


# ------------------------------------------------------------------ salud y CLI


async def test_health_endpoint_has_no_personal_data(env: Env) -> None:
    r = await env.client.get("/salud")
    assert r.status_code == 200
    assert r.json() == {"estado": "verde", "version": "0.1.0", "base_de_datos": True}


async def test_responses_carry_request_id_and_security_headers(env: Env) -> None:
    r = await env.client.get("/salud", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_vapid_generate_produces_usable_keys() -> None:
    """Las llaves generadas por la CLI funcionan con pywebpush (firma VAPID)."""
    from py_vapid import Vapid02

    from uno.cli import app

    out = CliRunner().invoke(app, ["vapid-generate"]).output
    values = dict(line.split("=", 1) for line in out.splitlines() if line.startswith("UNO_VAPID"))
    public, private = values["UNO_VAPID_PUBLIC_KEY"], values["UNO_VAPID_PRIVATE_KEY"]
    assert len(base64.urlsafe_b64decode(public + "==")) == 65  # punto sin comprimir
    vapid = Vapid02.from_string(private)
    headers = vapid.sign({"sub": "mailto:a@b.co", "aud": "https://fcm.googleapis.com"})
    assert headers["Authorization"].startswith("vapid ")
    derived = (
        base64.urlsafe_b64encode(
            vapid.public_key.public_bytes(
                __import__(
                    "cryptography.hazmat.primitives.serialization", fromlist=["x"]
                ).Encoding.X962,
                __import__(
                    "cryptography.hazmat.primitives.serialization", fromlist=["x"]
                ).PublicFormat.UncompressedPoint,
            )
        )
        .rstrip(b"=")
        .decode()
    )
    assert derived == public


def test_cli_create_user_and_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Flujo de administración local con SQLite: migrar, sembrar líneas, crear usuario, sembrar demo."""
    from uno.cli import app
    from uno.config import get_settings

    db = (tmp_path / "cli.db").as_posix()
    monkeypatch.setenv("UNO_DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    monkeypatch.setenv("UNO_ARGON2_TIME_COST", "1")
    monkeypatch.setenv("UNO_ARGON2_MEMORY_COST", "8")
    monkeypatch.setenv("UNO_ARGON2_PARALLELISM", "1")
    monkeypatch.setenv("UNO_EMAIL_BACKEND", "memory")
    get_settings.cache_clear()
    runner = CliRunner()
    try:
        assert runner.invoke(app, ["db-upgrade"]).exit_code == 0
        r = runner.invoke(app, ["seed-lines"])
        assert r.exit_code == 0 and "Líneas creadas: 3" in r.output
        assert "Líneas creadas: 0" in runner.invoke(app, ["seed-lines"]).output
        r = runner.invoke(
            app,
            [
                "create-user",
                "--name",
                "Ana Prueba",
                "--phone",
                "+573010000001",
                "--pin",
                "112233",
                "--email",
                "ana@ejemplo.com",
            ],
        )
        assert r.exit_code == 0, r.output
        assert "Usuario creado" in r.output
        dup = runner.invoke(
            app, ["create-user", "--name", "Ana", "--phone", "+573010000001", "--pin", "112233"]
        )
        assert dup.exit_code != 0
        r = runner.invoke(app, ["seed-demo"])
        assert r.exit_code == 0, r.output
        assert "+573000000002" in r.output
        assert runner.invoke(app, ["run-reminders"]).exit_code == 0
    finally:
        get_settings.cache_clear()
    # La sesión de demostración quedó con 4 médicos y 4 visitas hoy.
    eng = create_engine(f"sqlite:///{db}")
    with eng.connect() as c:
        assert c.execute(text("SELECT count(*) FROM doctor")).scalar() == 4
        assert c.execute(text("SELECT count(*) FROM visit")).scalar() == 4
        assert c.execute(text("SELECT count(*) FROM domain_event")).scalar() == 8
    eng.dispose()
