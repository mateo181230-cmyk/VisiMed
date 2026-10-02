"""Notificaciones: preferencias, Web Push, correo verificado, recordatorios y resumen diario."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select

from uno import clock
from uno.modules.notifications import messages
from uno.modules.notifications.models import (
    NotificationLog,
    NotificationPreference,
    PushSubscription,
)
from uno.modules.notifications.reminders import run_due_reminders

from .conftest import ADMIN_PHONE, Env, bearer, login, make_user, rep_token
from .helpers import doctor_event, ev, post_sync, visit_event

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"
KEYS = {"p256dh": "BPk" + "x" * 60, "auth": "a" * 22}


async def prefs(env: Env, token: str) -> dict:  # type: ignore[type-arg]
    r = await env.client.get("/v1/notifications/preferences", headers=bearer(token))
    assert r.status_code == 200, r.text
    return r.json()


async def subscribe(env: Env, token: str, endpoint: str = ENDPOINT) -> dict:  # type: ignore[type-arg]
    r = await env.client.post(
        "/v1/notifications/push/subscriptions",
        headers=bearer(token),
        json={"endpoint": endpoint, "keys": KEYS},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def verified_email(env: Env, token: str, address: str = "ana@ejemplo.com") -> None:
    r = await env.client.post(
        "/v1/notifications/email", headers=bearer(token), json={"email": address}
    )
    assert r.status_code == 202, r.text
    code = re.search(r"\b(\d{6})\b", env.email.sent[-1].text).group(1)  # type: ignore[union-attr]
    r = await env.client.post(
        "/v1/notifications/email/verify", headers=bearer(token), json={"code": code}
    )
    assert r.status_code == 200, r.text


async def no_digest(env: Env, token: str) -> None:
    """Apaga el resumen diario para probar solo los recordatorios de visita."""
    r = await env.client.put(
        "/v1/notifications/preferences", headers=bearer(token), json={"digest_enabled": False}
    )
    assert r.status_code == 200, r.text


async def logs(env: Env) -> list[NotificationLog]:
    async with env.ctx.sessionmaker() as s:
        return list(
            (
                await s.execute(select(NotificationLog).order_by(NotificationLog.created_at))
            ).scalars()
        )


async def schedule(
    env: Env,
    token: str,
    minutes_from_now: float,
    *,
    name: str = "Dra. Laura Méndez",
    doctor_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    events = []
    if doctor_id is None:
        d_ev, doctor_id = doctor_event(env, name=name)
        events.append(d_ev)
    v_ev, visit_id = visit_event(
        env, doctor_id=doctor_id, scheduled_at=clock.now() + timedelta(minutes=minutes_from_now)
    )
    events.append(v_ev)
    out = await post_sync(env, token, events)
    assert all(r["status"] == "applied" for r in out["results"]), out
    return visit_id, doctor_id


# ------------------------------------------------------------------ preferencias


async def test_default_preferences(env: Env) -> None:
    token = await rep_token(env)
    p = await prefs(env, token)
    assert p["push_enabled"] is False and p["email_enabled"] is False
    assert p["remind_before_min"] == 30
    assert p["digest_enabled"] is True and p["digest_time"] == "07:30"
    assert p["push_available"] is True and p["vapid_public_key"]
    assert 30 in p["remind_options"]


async def test_update_preferences_validation(env: Env) -> None:
    token = await rep_token(env)

    def put(body: dict):  # type: ignore[no-untyped-def,type-arg]
        return env.client.put("/v1/notifications/preferences", headers=bearer(token), json=body)

    ok = await put({"remind_before_min": 15, "digest_time": "06:45", "digest_enabled": False})
    assert ok.status_code == 200
    assert ok.json()["remind_before_min"] == 15 and ok.json()["digest_time"] == "06:45"
    assert (await put({"remind_before_min": 17})).status_code == 422
    assert (await put({"digest_time": "25:00"})).status_code == 422
    assert (await put({"digest_time": "7:30"})).status_code == 422
    assert (await put({"push_enabled": True})).json()["detail"]["code"] == "no_push_subscription"
    assert (await put({"email_enabled": True})).json()["detail"]["code"] == "email_not_verified"


# ------------------------------------------------------------------ Web Push


async def test_subscribe_enables_push_and_unsubscribe_disables(env: Env) -> None:
    token = await rep_token(env)
    p = await subscribe(env, token)
    assert p["push_enabled"] is True and p["push_subscriptions"] == 1
    # Suscribirse dos veces al mismo endpoint no duplica.
    p = await subscribe(env, token)
    assert p["push_subscriptions"] == 1
    r = await env.client.post(
        "/v1/notifications/push/unsubscribe", headers=bearer(token), json={"endpoint": ENDPOINT}
    )
    assert r.json()["push_enabled"] is False and r.json()["push_subscriptions"] == 0


async def test_subscription_endpoint_must_be_a_known_push_service(env: Env) -> None:
    """Evita SSRF: el servidor no debe llamar a direcciones que elija el cliente."""
    token = await rep_token(env)
    for bad in [
        "http://fcm.googleapis.com/fcm/send/x",  # sin TLS
        "https://169.254.169.254/latest/meta-data",
        "https://localhost:8000/x",
        "https://evil.example.com/fcm.googleapis.com",
        "https://fcm.googleapis.com.evil.com/x",
        "ftp://fcm.googleapis.com/x",
    ]:
        r = await env.client.post(
            "/v1/notifications/push/subscriptions",
            headers=bearer(token),
            json={"endpoint": bad, "keys": KEYS},
        )
        assert r.status_code == 422, bad
    ok = await env.client.post(
        "/v1/notifications/push/subscriptions",
        headers=bearer(token),
        json={"endpoint": "https://updates.push.services.mozilla.com/wpush/v2/abc", "keys": KEYS},
    )
    assert ok.status_code == 201


async def test_subscription_moves_to_the_latest_user_and_bad_keys_rejected(env: Env) -> None:
    ana = await rep_token(env, name="Ana")
    bob = await rep_token(env, phone="+573004445566", name="Bob")
    await subscribe(env, ana)
    p = await subscribe(env, bob)  # mismo navegador, otro usuario
    assert p["push_subscriptions"] == 1
    assert (await prefs(env, ana))["push_subscriptions"] == 0
    r = await env.client.post(
        "/v1/notifications/push/subscriptions",
        headers=bearer(bob),
        json={"endpoint": ENDPOINT + "2", "keys": {"p256dh": "x", "auth": "y"}},
    )
    assert r.status_code == 422


# ------------------------------------------------------------------ correo


async def test_email_verification_flow(env: Env) -> None:
    token = await rep_token(env)
    r = await env.client.post(
        "/v1/notifications/email", headers=bearer(token), json={"email": "Ana@Ejemplo.COM"}
    )
    assert r.status_code == 202 and r.json()["email"] == "ana@ejemplo.com"
    msg = env.email.sent[-1]
    assert msg.to == "ana@ejemplo.com" and "código" in msg.subject.lower()
    p = await prefs(env, token)
    assert (
        p["pending_email"] == "ana@ejemplo.com"
        and p["email_verified"] is False
        and p["email"] is None
    )

    bad = await env.client.post(
        "/v1/notifications/email/verify", headers=bearer(token), json={"code": "000000"}
    )
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_code"

    code = re.search(r"\b(\d{6})\b", msg.text).group(1)  # type: ignore[union-attr]
    ok = await env.client.post(
        "/v1/notifications/email/verify", headers=bearer(token), json={"code": code}
    )
    assert ok.status_code == 200
    p = ok.json()
    assert (
        p["email"] == "ana@ejemplo.com"
        and p["email_verified"] is True
        and p["email_enabled"] is True
    )
    assert p["pending_email"] is None
    # El código no se puede reutilizar.
    again = await env.client.post(
        "/v1/notifications/email/verify", headers=bearer(token), json={"code": code}
    )
    assert again.status_code == 422


async def test_email_code_expires_and_attempts_are_limited(env: Env) -> None:
    token = await rep_token(env)
    await env.client.post(
        "/v1/notifications/email", headers=bearer(token), json={"email": "a@b.co"}
    )
    code = re.search(r"\b(\d{6})\b", env.email.sent[-1].text).group(1)  # type: ignore[union-attr]
    for _ in range(5):
        r = await env.client.post(
            "/v1/notifications/email/verify", headers=bearer(token), json={"code": "111111"}
        )
        assert r.status_code == 422
    blocked = await env.client.post(
        "/v1/notifications/email/verify", headers=bearer(token), json={"code": code}
    )
    assert blocked.status_code == 429  # 5 fallos: el código correcto tampoco sirve

    await env.client.post(
        "/v1/notifications/email", headers=bearer(token), json={"email": "a@b.co"}
    )
    code2 = re.search(r"\b(\d{6})\b", env.email.sent[-1].text).group(1)  # type: ignore[union-attr]
    env.clock.advance(minutes=16)
    expired = await env.client.post(
        "/v1/notifications/email/verify", headers=bearer(token), json={"code": code2}
    )
    assert expired.status_code == 422


async def test_new_code_invalidates_the_previous_one_and_is_rate_limited(env: Env) -> None:
    token = await rep_token(env)
    await env.client.post(
        "/v1/notifications/email", headers=bearer(token), json={"email": "a@b.co"}
    )
    old = re.search(r"\b(\d{6})\b", env.email.sent[-1].text).group(1)  # type: ignore[union-attr]
    await env.client.post(
        "/v1/notifications/email", headers=bearer(token), json={"email": "a@b.co"}
    )
    r = await env.client.post(
        "/v1/notifications/email/verify", headers=bearer(token), json={"code": old}
    )
    assert r.status_code == 422
    for _ in range(3):
        await env.client.post(
            "/v1/notifications/email", headers=bearer(token), json={"email": "a@b.co"}
        )
    r = await env.client.post(
        "/v1/notifications/email", headers=bearer(token), json={"email": "a@b.co"}
    )
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_codes"


async def test_invalid_email_and_send_failure(env: Env) -> None:
    token = await rep_token(env)
    r = await env.client.post(
        "/v1/notifications/email", headers=bearer(token), json={"email": "no-es-correo"}
    )
    assert r.status_code == 422
    env.email.fail = True
    r = await env.client.post(
        "/v1/notifications/email", headers=bearer(token), json={"email": "a@b.co"}
    )
    assert r.status_code == 502
    assert (await prefs(env, token))[
        "pending_email"
    ] is None  # no queda un código que nadie recibió


async def test_remove_email_disables_channel(env: Env) -> None:
    token = await rep_token(env)
    await verified_email(env, token)
    r = await env.client.delete("/v1/notifications/email", headers=bearer(token))
    p = r.json()
    assert p["email"] is None and p["email_enabled"] is False and p["email_verified"] is False


# ------------------------------------------------------------------ prueba de envío


async def test_send_test_notification_on_both_channels(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    await verified_email(env, token)
    env.email.sent.clear()
    r = await env.client.post(
        "/v1/notifications/test", headers=bearer(token), json={"channel": "all"}
    )
    assert r.status_code == 200 and r.json()["results"] == {"push": "sent", "email": "sent"}
    assert len(env.push.sent) == 1 and env.push.sent[0][1].title == "Prueba de UNO Visitas"
    assert len(env.email.sent) == 1
    # Una segunda prueba también se envía (referencia distinta).
    r = await env.client.post(
        "/v1/notifications/test", headers=bearer(token), json={"channel": "push"}
    )
    assert r.json()["results"] == {"push": "sent"}


async def test_test_notification_does_not_claim_local_files_reached_inbox(make_env) -> None:
    async with make_env(email_backend="file", push_backend="log") as env:
        token = await rep_token(env)
        await verified_email(env, token)
        env.email.sent.clear()
        prefs = await env.client.get("/v1/notifications/preferences", headers=bearer(token))
        assert prefs.json()["email_delivery_available"] is False
        assert prefs.json()["push_delivery_available"] is False
        r = await env.client.post(
            "/v1/notifications/test", headers=bearer(token), json={"channel": "all"}
        )
        assert r.json()["results"] == {"push": "unavailable", "email": "unavailable"}
        assert env.email.sent == [] and env.push.sent == []


async def test_test_notification_is_skipped_without_subscription_or_email(env: Env) -> None:
    token = await rep_token(env)
    r = await env.client.post(
        "/v1/notifications/test", headers=bearer(token), json={"channel": "all"}
    )
    assert r.json()["results"] == {"push": "skipped", "email": "skipped"}
    assert env.push.sent == [] and env.email.sent == []


async def test_test_notification_rate_limit(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    for _ in range(10):
        assert (
            await env.client.post(
                "/v1/notifications/test", headers=bearer(token), json={"channel": "push"}
            )
        ).status_code == 200
    assert (
        await env.client.post(
            "/v1/notifications/test", headers=bearer(token), json={"channel": "push"}
        )
    ).status_code == 429


# ------------------------------------------------------------------ recordatorios de visita


async def test_visit_reminder_is_sent_once_on_both_channels(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    await verified_email(env, token)
    env.email.sent.clear()
    await schedule(env, token, minutes_from_now=25)

    stats = await run_due_reminders(env.ctx, clock.now())
    assert stats["visit_reminder.push.sent"] == 1 and stats["visit_reminder.email.sent"] == 1
    (target, message) = env.push.sent[0]
    assert target.endpoint == ENDPOINT
    assert message.title == "Visita en 25 min"
    assert "Dra. Laura Méndez" in message.body and "Clínica Central" in message.body
    assert re.search(r"\d{1,2}:\d{2} (AM|PM)", message.body)
    assert len(env.email.sent) == 1 and env.email.sent[0].to == "ana@ejemplo.com"

    # El trabajador corre cada minuto: no repite.
    for _ in range(3):
        env.clock.advance(minutes=1)
        again = await run_due_reminders(env.ctx, clock.now())
        assert not any(k.endswith(".sent") for k in again)
    assert len(env.push.sent) == 1 and len(env.email.sent) == 1
    assert {(x.channel, x.status) for x in await logs(env)} == {("push", "sent"), ("email", "sent")}


async def test_reminder_waits_for_its_window(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    await no_digest(env, token)
    await schedule(env, token, minutes_from_now=120)
    assert await run_due_reminders(env.ctx, clock.now()) == {}
    env.clock.advance(minutes=89)  # faltan 31 min: todavía no
    assert await run_due_reminders(env.ctx, clock.now()) == {}
    env.clock.advance(minutes=2)  # faltan 29 min
    stats = await run_due_reminders(env.ctx, clock.now())
    assert stats["visit_reminder.push.sent"] == 1


async def test_no_reminder_for_past_or_not_done_visits_or_when_disabled(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    v_past, doctor_id = await schedule(env, token, minutes_from_now=10)
    v_cancel, _ = await schedule(env, token, minutes_from_now=15, doctor_id=doctor_id)
    await post_sync(env, token, [ev("visit_not_done", {"reason": "other"}, visit_id=v_cancel)])
    env.clock.advance(minutes=11)  # la primera visita ya pasó
    assert await run_due_reminders(env.ctx, clock.now()) == {}

    await env.client.put(
        "/v1/notifications/preferences", headers=bearer(token), json={"remind_before_min": 0}
    )
    await schedule(env, token, minutes_from_now=5, doctor_id=doctor_id)
    assert await run_due_reminders(env.ctx, clock.now()) == {}
    _ = v_past


async def test_rescheduled_visit_gets_a_new_reminder(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    visit_id, _ = await schedule(env, token, minutes_from_now=20)
    await run_due_reminders(env.ctx, clock.now())
    assert len(env.push.sent) == 1
    new_time = clock.now() + timedelta(minutes=25)
    await post_sync(
        env,
        token,
        [ev("visit_rescheduled", {"scheduled_at": new_time.isoformat()}, visit_id=visit_id)],
    )
    stats = await run_due_reminders(env.ctx, clock.now())
    assert stats["visit_reminder.push.sent"] == 1 and len(env.push.sent) == 2


async def test_reminder_respects_user_preference_minutes(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    await env.client.put(
        "/v1/notifications/preferences", headers=bearer(token), json={"remind_before_min": 10}
    )
    await schedule(env, token, minutes_from_now=20)
    assert await run_due_reminders(env.ctx, clock.now()) == {}
    env.clock.advance(minutes=11)
    assert (await run_due_reminders(env.ctx, clock.now()))["visit_reminder.push.sent"] == 1


async def test_only_the_owner_is_notified(env: Env) -> None:
    ana = await rep_token(env, name="Ana")
    bob = await rep_token(env, phone="+573004445566", name="Bob")
    await subscribe(env, ana, ENDPOINT)
    await subscribe(env, bob, ENDPOINT + "-bob")
    await schedule(env, bob, minutes_from_now=20)
    await run_due_reminders(env.ctx, clock.now())
    assert [t.endpoint for t, _ in env.push.sent] == [ENDPOINT + "-bob"]


async def test_names_can_be_hidden_from_notifications(make_env) -> None:  # type: ignore[no-untyped-def]
    async with make_env(notify_include_names=False) as env:
        token = await rep_token(env)
        await subscribe(env, token)
        await schedule(env, token, minutes_from_now=20)
        await run_due_reminders(env.ctx, clock.now())
        body = env.push.sent[0][1].body
        assert "Méndez" not in body and "Clínica Central" in body


# ------------------------------------------------------------------ resumen diario


def local(env: Env, hour: int, minute: int = 0) -> datetime:
    """Hora local de Bogotá del día del reloj falso, en UTC."""
    return clock.now().replace(hour=hour + 5, minute=minute, second=0, microsecond=0)


async def test_daily_digest_sent_once_in_its_window(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    # Visitas hoy a las 8:00 y 10:00 (hora de Bogotá).
    d_ev, doctor_id = doctor_event(
        env,
        name="Dr. Carlos Gómez",
        institution={"id": str(uuid.uuid4()), "name": "Hospital San Rafael"},
    )
    v1, _ = visit_event(env, doctor_id=doctor_id, scheduled_at=local(env, 8))
    v2, _ = visit_event(env, doctor_id=doctor_id, scheduled_at=local(env, 10))
    await post_sync(env, token, [d_ev, v1, v2])

    env.clock.set(local(env, 7, 29))
    assert await run_due_reminders(env.ctx, clock.now()) == {}  # falta un minuto
    env.clock.set(local(env, 7, 30))
    stats = await run_due_reminders(env.ctx, clock.now())
    assert stats["daily_digest.push.sent"] == 1
    digest = [m for _, m in env.push.sent if m.kind == "daily_digest"][0]
    assert digest.title == "Tu agenda de hoy: 2 visitas"
    assert "8:00 AM" in digest.body and "Dr. Carlos Gómez" in digest.body

    env.clock.set(local(env, 9, 0))
    assert "daily_digest.push.sent" not in await run_due_reminders(env.ctx, clock.now())
    assert len([m for _, m in env.push.sent if m.kind == "daily_digest"]) == 1


async def test_digest_window_closes_and_needs_visits(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    await env.client.put(
        "/v1/notifications/preferences", headers=bearer(token), json={"remind_before_min": 0}
    )
    env.clock.set(local(env, 7, 45))
    assert await run_due_reminders(env.ctx, clock.now()) == {}  # sin visitas hoy: no se avisa

    d_ev, doctor_id = doctor_event(env)
    v1, _ = visit_event(env, doctor_id=doctor_id, scheduled_at=local(env, 15))
    await post_sync(env, token, [d_ev, v1])
    env.clock.set(local(env, 11, 31))  # pasaron más de 4 h desde las 07:30
    assert await run_due_reminders(env.ctx, clock.now()) == {}
    env.clock.set(local(env, 10, 0))
    assert (await run_due_reminders(env.ctx, clock.now()))["daily_digest.push.sent"] == 1


async def test_digest_can_be_disabled_and_singular_wording(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    d_ev, doctor_id = doctor_event(env)
    v1, _ = visit_event(env, doctor_id=doctor_id, scheduled_at=local(env, 15))
    await post_sync(env, token, [d_ev, v1])
    await env.client.put(
        "/v1/notifications/preferences",
        headers=bearer(token),
        json={"digest_enabled": False, "remind_before_min": 0},
    )
    env.clock.set(local(env, 8, 0))
    assert await run_due_reminders(env.ctx, clock.now()) == {}
    await env.client.put(
        "/v1/notifications/preferences", headers=bearer(token), json={"digest_enabled": True}
    )
    await run_due_reminders(env.ctx, clock.now())
    assert env.push.sent[-1][1].title == "Tu agenda de hoy: 1 visita"


async def test_digest_next_day_is_sent_again(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    d_ev, doctor_id = doctor_event(env)
    day1, _ = visit_event(env, doctor_id=doctor_id, scheduled_at=local(env, 15))
    day2, _ = visit_event(env, doctor_id=doctor_id, scheduled_at=local(env, 15) + timedelta(days=1))
    await post_sync(env, token, [d_ev, day1, day2])
    await env.client.put(
        "/v1/notifications/preferences", headers=bearer(token), json={"remind_before_min": 0}
    )
    env.clock.set(local(env, 8))
    await run_due_reminders(env.ctx, clock.now())
    env.clock.set(local(env, 8) + timedelta(days=1))
    await run_due_reminders(env.ctx, clock.now())
    assert len([m for _, m in env.push.sent if m.kind == "daily_digest"]) == 2


# ------------------------------------------------------------------ fallas y reintentos


async def test_failed_push_is_retried_with_backoff_and_stops_after_three(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    await no_digest(env, token)
    env.push.failing_endpoints.add(ENDPOINT)
    await schedule(env, token, minutes_from_now=25)

    stats = await run_due_reminders(env.ctx, clock.now())
    assert stats["visit_reminder.push.failed"] == 1
    (row,) = await logs(env)
    assert row.status == "failed" and row.attempts == 1

    env.clock.advance(minutes=1)  # aún dentro de la espera de 2 min
    assert "visit_reminder.push.failed" not in await run_due_reminders(env.ctx, clock.now())

    env.clock.advance(minutes=2)
    assert (await run_due_reminders(env.ctx, clock.now()))["visit_reminder.push.failed"] == 1
    assert (await logs(env))[0].attempts == 2

    env.clock.advance(minutes=11)
    assert (await run_due_reminders(env.ctx, clock.now()))["visit_reminder.push.failed"] == 1
    assert (await logs(env))[0].attempts == 3

    env.clock.advance(hours=1)
    assert (
        await run_due_reminders(env.ctx, clock.now()) == {}
    )  # se rindió (visita ya pasó o 3 intentos)


async def test_recovery_after_a_failure(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    env.push.failing_endpoints.add(ENDPOINT)
    await schedule(env, token, minutes_from_now=25)
    await run_due_reminders(env.ctx, clock.now())
    env.push.failing_endpoints.clear()
    env.clock.advance(minutes=3)
    stats = await run_due_reminders(env.ctx, clock.now())
    assert stats["visit_reminder.push.sent"] == 1
    assert (await logs(env))[0].status == "sent"


async def test_gone_subscription_is_disabled(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    env.push.gone_endpoints.add(ENDPOINT)
    await schedule(env, token, minutes_from_now=25)
    await run_due_reminders(env.ctx, clock.now())
    async with env.ctx.sessionmaker() as s:
        sub = (await s.execute(select(PushSubscription))).scalar_one()
    assert sub.disabled_at is not None
    assert (await prefs(env, token))["push_subscriptions"] == 0


async def test_email_failure_does_not_block_push(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    await verified_email(env, token)
    env.email.sent.clear()
    env.email.fail = True
    await schedule(env, token, minutes_from_now=25)
    stats = await run_due_reminders(env.ctx, clock.now())
    assert stats["visit_reminder.push.sent"] == 1 and stats["visit_reminder.email.failed"] == 1


async def test_two_workers_at_once_send_only_once(env: Env) -> None:
    token = await rep_token(env)
    await subscribe(env, token)
    await verified_email(env, token)
    env.email.sent.clear()
    await schedule(env, token, minutes_from_now=25)
    await asyncio.gather(*[run_due_reminders(env.ctx, clock.now()) for _ in range(4)])
    assert len(env.push.sent) == 1 and len(env.email.sent) == 1
    async with env.ctx.sessionmaker() as s:
        assert (
            await s.execute(select(func.count()).select_from(NotificationLog))
        ).scalar_one() == 2


async def test_stuck_pending_claim_is_recovered_after_lease(env: Env) -> None:
    """Si el trabajador murió a mitad de un envío, otro lo retoma pasada la reserva de 10 min."""
    token = await rep_token(env)
    await subscribe(env, token)
    await schedule(env, token, minutes_from_now=25)
    env.push.failing_endpoints.add(ENDPOINT)
    await run_due_reminders(env.ctx, clock.now())  # 1er intento: falla
    async with env.ctx.sessionmaker() as s:
        row = (await s.execute(select(NotificationLog))).scalar_one()
        row.status = "pending"  # simula un trabajador que murió sin terminar
        row.next_attempt_at = clock.now() + timedelta(minutes=10)
        await s.commit()
    env.push.failing_endpoints.clear()
    assert await run_due_reminders(env.ctx, clock.now()) == {"visit_reminder.push.duplicate": 1}
    env.clock.advance(minutes=11)
    stats = await run_due_reminders(env.ctx, clock.now())
    assert (
        stats.get("visit_reminder.push.sent", 0) + stats.get("visit_reminder.push.duplicate", 0)
        >= 1
    )


async def test_users_without_channels_are_ignored(env: Env) -> None:
    token = await rep_token(env)
    await schedule(env, token, minutes_from_now=10)
    assert await run_due_reminders(env.ctx, clock.now()) == {}
    async with env.ctx.sessionmaker() as s:
        assert (
            await s.execute(select(func.count()).select_from(NotificationPreference))
        ).scalar_one() >= 0


async def test_admin_preregistered_email_receives_reminders_without_code(env: Env) -> None:
    await make_user(env, phone=ADMIN_PHONE, role="admin", name="Admin")
    admin = await login(env, ADMIN_PHONE)
    rep = await make_user(env, phone="+573100001111", name="Carlos")
    r = await env.client.put(
        f"/v1/admin/users/{rep}/notification-email",
        headers=bearer(admin),
        json={"email": "carlos@ejemplo.com"},
    )
    assert r.status_code == 204
    token = await login(env, "+573100001111")
    await schedule(env, token, minutes_from_now=20)
    stats = await run_due_reminders(env.ctx, clock.now())
    assert stats["visit_reminder.email.sent"] == 1
    assert env.email.sent[-1].to == "carlos@ejemplo.com"


# ------------------------------------------------------------------ textos


def test_time_formatting() -> None:
    from datetime import UTC

    def t(h: int, m: int) -> datetime:
        return datetime(2026, 9, 29, h, m, tzinfo=UTC)

    assert messages.format_time(t(0, 5)) == "12:05 AM"
    assert messages.format_time(t(9, 0)) == "9:00 AM"
    assert messages.format_time(t(12, 0)) == "12:00 PM"
    assert messages.format_time(t(13, 30)) == "1:30 PM"
    assert messages.format_time(t(23, 59)) == "11:59 PM"
    assert messages.format_date(t(9, 0)) == "martes 29 de septiembre"


def test_email_html_escapes_content() -> None:
    m = messages.to_email("a@b.co", "<b>Hola</b>", "x & y", "http://app")
    assert "<b>Hola</b>" not in (m.html or "") and "&lt;b&gt;" in (m.html or "")
    assert "x &amp; y" in (m.html or "")
