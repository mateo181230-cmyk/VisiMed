from __future__ import annotations

import asyncio
import threading
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from uno.modules.auth import service, throttle
from uno.modules.auth.models import AuthAttemptLock, LoginAttempt

from .conftest import PIN, REP_PHONE, Env, make_user


async def test_concurrent_wrong_pins_cannot_bypass_phone_limit(env: Env) -> None:
    await make_user(env)
    responses = await asyncio.gather(
        *(
            env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": "000000"})
            for _ in range(16)
        )
    )
    assert sorted(r.status_code for r in responses) == [401] * 5 + [429] * 11
    async with env.ctx.sessionmaker() as session:
        assert (await session.scalar(select(func.count()).select_from(LoginAttempt))) == 5


async def test_concurrent_unknown_phones_cannot_bypass_ip_limit(env: Env) -> None:
    responses = await asyncio.gather(
        *(
            env.client.post(
                "/v1/auth/login", json={"phone": f"+57310000{i:04d}", "pin": "000000"}
            )
            for i in range(25)
        )
    )
    assert sorted(r.status_code for r in responses) == [401] * 20 + [429] * 5


async def test_failures_at_same_timestamp_as_success_still_lock_account(env: Env) -> None:
    await make_user(env)
    assert (
        await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": PIN})
    ).status_code == 200
    for _ in range(5):
        assert (
            await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": "000000"})
        ).status_code == 401
    assert (
        await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": PIN})
    ).status_code == 429


async def test_success_keeps_concurrent_pending_failures_counted(env: Env) -> None:
    await make_user(env)
    async with env.ctx.sessionmaker() as first, env.ctx.sessionmaker() as second:
        pending = await throttle.reserve(
            first, env.settings, purpose="login", phone=REP_PHONE, ip="127.0.0.1", now=env.clock.now()
        )
        valid = await throttle.reserve(
            second, env.settings, purpose="login", phone=REP_PHONE, ip="127.0.0.1", now=env.clock.now()
        )
        await throttle.finish_login(second, valid, success=True, now=env.clock.now())
        await second.commit()
        await throttle.finish_login(first, pending, success=False, now=env.clock.now())
        await first.commit()
    for _ in range(4):
        assert (
            await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": "000000"})
        ).status_code == 401
    assert (
        await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": "000000"})
    ).status_code == 429


async def test_successful_logins_do_not_consume_failure_quota(env: Env) -> None:
    await make_user(env)
    for _ in range(25):
        assert (
            await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": PIN})
        ).status_code == 200


async def test_old_auth_guards_and_attempts_are_pruned(env: Env) -> None:
    old_at = env.clock.now() - timedelta(days=2)
    async with env.ctx.sessionmaker() as session:
        session.add(AuthAttemptLock(key="login:phone:+573000000999", touched_at=old_at))
        old = LoginAttempt(phone="+573000000999", ip="127.0.0.1", at=old_at, success=False)
        session.add(old)
        await session.commit()
        old_id = old.id
    await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": "000000"})
    async with env.ctx.sessionmaker() as session:
        assert await session.get(LoginAttempt, old_id) is None
        assert await session.get(AuthAttemptLock, "login:phone:+573000000999") is None


def test_ipv6_rotation_within_64_shares_quota() -> None:
    assert throttle.ip_key("2001:db8:abcd:1234::1") == throttle.ip_key("2001:db8:abcd:1234:ffff::9")
    assert throttle.ip_key("::ffff:192.0.2.1") == throttle.ip_key("192.0.2.1")


@pytest.mark.parametrize("phone", ["+123456789012345678901", "+57٣٠٠١١١٢٢٣٣"])
async def test_invalid_normalized_phone_is_rejected_before_hashing(
    env: Env, monkeypatch: pytest.MonkeyPatch, phone: str
) -> None:
    def must_not_hash(*args):
        pytest.fail("Invalid phone reached Argon2")

    monkeypatch.setattr(service, "dummy_verify", must_not_hash)
    response = await env.client.post("/v1/auth/login", json={"phone": phone, "pin": "000000"})
    assert response.status_code == 422


async def test_argon2_work_runs_off_the_event_loop(env: Env, monkeypatch) -> None:
    main_thread = threading.get_ident()
    seen = []
    for name in ("hash_pin", "verify_pin", "dummy_verify"):
        original = getattr(service, name)

        def capture(*args, original=original, name=name):
            seen.append((name, threading.get_ident()))
            return original(*args)

        monkeypatch.setattr(service, name, capture)
    await make_user(env)
    await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": PIN})
    await env.client.post("/v1/auth/login", json={"phone": "+573000000099", "pin": "000000"})
    assert {name for name, _ in seen} == {"hash_pin", "verify_pin", "dummy_verify"}
    assert all(thread != main_thread for _, thread in seen)


def registration_payload(**values):
    return {
        "full_name": "Laura Piloto",
        "phone": "+573109876543",
        "email": "laura@example.com",
        "pin": "123456",
        "invite_code": "wrong-code",
        **values,
    }


async def test_unicode_invite_is_compared_without_server_error(make_env) -> None:
    async with make_env(pilot_invite_code="Invitación-Bogotá") as env:
        wrong = await env.client.post(
            "/v1/auth/register", json=registration_payload(invite_code="Invitación-otra")
        )
        assert wrong.status_code == 403
        valid = await env.client.post(
            "/v1/auth/register", json=registration_payload(invite_code="Invitación-Bogotá")
        )
        assert valid.status_code == 201


async def test_concurrent_invite_guesses_are_limited_by_ip(make_env) -> None:
    async with make_env(pilot_invite_code="correct-code") as env:
        responses = await asyncio.gather(
            *(
                env.client.post(
                    "/v1/auth/register",
                    json=registration_payload(phone=f"+57310000{i:04d}"),
                )
                for i in range(25)
            )
        )
        assert sorted(r.status_code for r in responses) == [403] * 20 + [429] * 5
        env.clock.advance(minutes=16)
        assert (
            await env.client.post(
                "/v1/auth/register", json=registration_payload(invite_code="correct-code")
            )
        ).status_code == 201


async def test_registration_attempts_do_not_use_login_quota(make_env) -> None:
    async with make_env(pilot_invite_code="correct-code") as env:
        await make_user(env)
        for _ in range(5):
            await env.client.post("/v1/auth/register", json=registration_payload())
        blocked = await env.client.post("/v1/auth/register", json=registration_payload())
        assert blocked.status_code == 429
        assert "retry-after" in blocked.headers
        assert (
            await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": PIN})
        ).status_code == 200
