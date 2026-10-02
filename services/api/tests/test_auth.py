from __future__ import annotations

import pytest

from .conftest import (
    ADMIN_PHONE,
    OTHER_PHONE,
    PIN,
    REP_PHONE,
    Env,
    bearer,
    login,
    make_user,
    rep_token,
)

WHITELIST_PATHS = {
    "/salud",
    "/v1/auth/login",
    "/v1/auth/register",
    "/v1/auth/refresh",
    "/v1/auth/logout",
}


async def test_registration_requires_invite(make_env) -> None:
    payload = {
        "full_name": "Laura Piloto",
        "phone": "+573109876543",
        "email": "laura@example.com",
        "pin": "123456",
        "invite_code": "incorrecto",
    }
    async with make_env(pilot_invite_code="secreto-piloto") as env:
        r = await env.client.post("/v1/auth/register", json=payload)
        assert r.status_code == 403
        r = await env.client.post(
            "/v1/auth/register", json={**payload, "invite_code": "secreto-piloto"}
        )
        assert r.status_code == 201
        assert r.json()["user"]["role"] == "rep"
        assert r.json()["user"]["phone"] == "+573109876543"
        prefs = await env.client.get(
            "/v1/notifications/preferences",
            headers=bearer(r.json()["access_token"]),
        )
        assert prefs.json()["email"] == "laura@example.com"
        assert prefs.json()["email_verified"] is False
        assert (
            await env.client.post(
                "/v1/auth/login", json={"phone": payload["phone"], "pin": payload["pin"]}
            )
        ).status_code == 200
        repeated = await env.client.post(
            "/v1/auth/register", json={**payload, "invite_code": "secreto-piloto"}
        )
        assert repeated.status_code == 409
    async with make_env() as env:
        assert (
            await env.client.post(
                "/v1/auth/register", json={**payload, "invite_code": "secreto-piloto"}
            )
        ).status_code == 403


async def test_login_ok_sets_httponly_refresh_cookie(env: Env) -> None:
    await make_user(env)
    r = await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": PIN})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "rep"
    set_cookie = r.headers["set-cookie"].lower()
    assert "uno_refresh=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    assert "path=/v1/auth" in set_cookie


async def test_login_accepts_phone_with_spaces(env: Env) -> None:
    await make_user(env)
    r = await env.client.post("/v1/auth/login", json={"phone": "+57 300 111 2233", "pin": PIN})
    assert r.status_code == 200


async def test_wrong_pin_and_unknown_phone_give_same_error(env: Env) -> None:
    await make_user(env)
    wrong = await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": "000000"})
    unknown = await env.client.post("/v1/auth/login", json={"phone": OTHER_PHONE, "pin": "000000"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_inactive_user_cannot_login(env: Env) -> None:
    from sqlalchemy import update

    from uno.modules.auth.models import User

    await make_user(env)
    async with env.ctx.sessionmaker() as s:
        await s.execute(update(User).values(is_active=False))
        await s.commit()
    r = await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": PIN})
    assert r.status_code == 401


async def test_rate_limit_blocks_after_five_failures_even_with_correct_pin(env: Env) -> None:
    await make_user(env)
    for _ in range(5):
        r = await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": "000000"})
        assert r.status_code == 401
    r = await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": PIN})
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "too_many_attempts"
    assert "retry-after" in r.headers


async def test_rate_limit_window_expires(env: Env) -> None:
    await make_user(env)
    for _ in range(5):
        await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": "000000"})
    env.clock.advance(minutes=16)
    r = await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": PIN})
    assert r.status_code == 200


async def test_success_resets_failure_count(env: Env) -> None:
    await make_user(env)
    for _ in range(4):
        await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": "000000"})
    assert (
        await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": PIN})
    ).status_code == 200
    for _ in range(4):
        r = await env.client.post("/v1/auth/login", json={"phone": REP_PHONE, "pin": "000000"})
        assert r.status_code == 401  # no llegó a 5 desde el último ingreso


async def test_me_requires_token(env: Env) -> None:
    assert (await env.client.get("/v1/me")).status_code == 401
    assert (await env.client.get("/v1/me", headers=bearer("basura"))).status_code == 401


async def test_access_token_expires_after_24h(env: Env) -> None:
    token = await rep_token(env)
    assert (await env.client.get("/v1/me", headers=bearer(token))).status_code == 200
    env.clock.advance(hours=24, minutes=1)
    r = await env.client.get("/v1/me", headers=bearer(token))
    assert r.status_code == 401


async def test_refresh_rotates_and_old_token_reuse_revokes_family(env: Env) -> None:
    await make_user(env)
    await login(env)
    first = env.client.cookies.get("uno_refresh")
    r = await env.client.post("/v1/auth/refresh")
    assert r.status_code == 200
    second = env.client.cookies.get("uno_refresh")
    assert first != second

    # Reutilizar el token ya rotado, pasada la tolerancia, es señal de robo: cae toda la familia.
    env.clock.advance(minutes=1)
    env.client.cookies.set("uno_refresh", first, path="/v1/auth")
    assert (await env.client.post("/v1/auth/refresh")).status_code == 401
    env.client.cookies.set("uno_refresh", second, path="/v1/auth")
    assert (await env.client.post("/v1/auth/refresh")).status_code == 401


async def test_refresh_within_grace_is_tolerated(env: Env) -> None:
    await make_user(env)
    await login(env)
    first = env.client.cookies.get("uno_refresh")
    assert (await env.client.post("/v1/auth/refresh")).status_code == 200
    env.clock.advance(seconds=3)
    env.client.cookies.set("uno_refresh", first, path="/v1/auth")
    assert (await env.client.post("/v1/auth/refresh")).status_code == 200


async def test_refresh_expires_after_30_days(env: Env) -> None:
    await make_user(env)
    await login(env)
    env.clock.advance(days=31)
    assert (await env.client.post("/v1/auth/refresh")).status_code == 401


async def test_refresh_without_cookie_is_401(env: Env) -> None:
    assert (await env.client.post("/v1/auth/refresh")).status_code == 401


async def test_logout_revokes_the_family(env: Env) -> None:
    await make_user(env)
    await login(env)
    token = env.client.cookies.get("uno_refresh")
    assert (await env.client.post("/v1/auth/logout")).status_code == 204
    env.client.cookies.set("uno_refresh", token, path="/v1/auth")
    assert (await env.client.post("/v1/auth/refresh")).status_code == 401


async def test_every_route_requires_auth_except_whitelist(env: Env) -> None:
    """T1.2 CA1: ninguna ruta queda sin autenticación fuera de la lista blanca."""
    # Se recorre el contrato OpenAPI: es la lista pública y completa de rutas de negocio.
    checked = 0
    for path, methods in env.app.openapi()["paths"].items():
        if path in WHITELIST_PATHS:
            continue
        concrete = path.replace("{user_id}", "00000000-0000-0000-0000-000000000001")
        for method in methods:
            r = await env.client.request(method.upper(), concrete, json={})
            assert r.status_code == 401, f"{method.upper()} {path} respondió {r.status_code}"
            checked += 1
    assert checked >= 10


async def test_docs_routes_are_not_business_routes(env: Env) -> None:
    # /docs y /openapi.json existen (FastAPI); no exponen datos.
    assert (await env.client.get("/openapi.json")).status_code == 200


@pytest.mark.parametrize("path", ["/v1/admin/users"])
async def test_rep_cannot_use_admin_routes(env: Env, path: str) -> None:
    token = await rep_token(env)
    assert (await env.client.get(path, headers=bearer(token))).status_code == 403


async def test_admin_creates_user_with_preregistered_verified_email(env: Env) -> None:
    await make_user(env, phone=ADMIN_PHONE, role="admin", name="Admin")
    token = await login(env, ADMIN_PHONE)
    r = await env.client.post(
        "/v1/admin/users",
        headers=bearer(token),
        json={
            "full_name": "Carlos Visitador",
            "phone": "+57 310 000 1111",
            "pin": "112233",
            "email": "Carlos@Ejemplo.com",
        },
    )
    assert r.status_code == 201
    assert r.json()["phone"] == "+573100001111"
    # El nuevo usuario ya tiene el correo verificado y activo, sin código.
    t2 = await login(env, "+573100001111", "112233")
    prefs = (await env.client.get("/v1/notifications/preferences", headers=bearer(t2))).json()
    assert prefs["email"] == "carlos@ejemplo.com"
    assert prefs["email_verified"] is True
    assert prefs["email_enabled"] is True


async def test_admin_duplicate_phone_and_invalid_input(env: Env) -> None:
    await make_user(env, phone=ADMIN_PHONE, role="admin", name="Admin")
    token = await login(env, ADMIN_PHONE)
    body = {"full_name": "Otro", "phone": ADMIN_PHONE, "pin": "112233"}
    assert (
        await env.client.post("/v1/admin/users", headers=bearer(token), json=body)
    ).status_code == 409
    bad_pin = {**body, "phone": "+573100002222", "pin": "abc123"}
    assert (
        await env.client.post("/v1/admin/users", headers=bearer(token), json=bad_pin)
    ).status_code == 422
    bad_phone = {**body, "phone": "3100002222"}
    assert (
        await env.client.post("/v1/admin/users", headers=bearer(token), json=bad_phone)
    ).status_code == 422
    bad_role = {**body, "phone": "+573100002222", "role": "root"}
    assert (
        await env.client.post("/v1/admin/users", headers=bearer(token), json=bad_role)
    ).status_code == 422
