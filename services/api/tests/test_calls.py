"""Llamadas de resumen: planear, marcar, reintentar y convertir la conversación en fichas."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from uno import clock
from uno.events import FORBIDDEN_KEYS, DomainEvent
from uno.modules.agenda.models import Visit
from uno.modules.calls import service
from uno.modules.calls.models import Call, CallVisit, VisitReport
from uno.modules.calls.provider import (
    ElevenLabsProvider,
    FakeOutcome,
    FakeProvider,
    ProviderError,
    canned_data,
    parse_conversation,
)
from uno.modules.calls.routes import sign

from .conftest import REP_PHONE, Env, make_user, rep_token
from .helpers import arrived_event, doctor_event, finished_event, location, post_sync, visit_event

SECRET = "whsec-test-secret"


# ------------------------------------------------------------------ ayudantes


def calls_env(make_env: Any, **overrides: Any) -> Any:
    return make_env(call_backend="fake", elevenlabs_webhook_secret=SECRET, **overrides)


def fake(env: Env) -> FakeProvider:
    provider = env.ctx.voice_provider
    assert isinstance(provider, FakeProvider)
    return provider


async def finish_visits(
    env: Env,
    token: str,
    count: int = 1,
    *,
    gap_min: int = 10,
    institution_name: str = "Clínica Central",
) -> list[uuid.UUID]:
    """El visitador agenda, llega y termina ``count`` visitas (todas quedan ``finished``)."""
    institution = {"id": str(uuid.uuid4()), "name": institution_name, "city": "Bogotá"}
    ids: list[uuid.UUID] = []
    for n in range(count):
        when = clock.now() - timedelta(minutes=gap_min * (count - n))
        d_ev, doctor_id = doctor_event(
            env, name=f"Dra. Médica {n + 1}", institution=institution, ts=when - timedelta(hours=2)
        )
        v_ev, visit_id = visit_event(
            env, doctor_id=doctor_id, scheduled_at=when, ts=when - timedelta(hours=1)
        )
        loc = location(4.6765, -74.0481)
        body = await post_sync(
            env,
            token,
            [
                d_ev,
                v_ev,
                arrived_event(visit_id, loc, ts=when),
                finished_event(visit_id, loc, ts=when + timedelta(minutes=8)),
            ],
        )
        assert all(r["status"] == "applied" for r in body["results"]), body["results"]
        ids.append(visit_id)
    return ids


async def visit_status(env: Env, visit_id: uuid.UUID) -> str:
    async with env.ctx.sessionmaker() as s:
        visit = await s.get(Visit, visit_id)
    assert visit is not None
    return visit.status


async def all_calls(env: Env) -> list[Call]:
    async with env.ctx.sessionmaker() as s:
        return list((await s.execute(select(Call).order_by(Call.created_at))).scalars())


async def call_visit_ids(env: Env, call_id: uuid.UUID) -> list[uuid.UUID]:
    async with env.ctx.sessionmaker() as s:
        rows = await s.execute(
            select(CallVisit.visit_id)
            .where(CallVisit.call_id == call_id)
            .order_by(CallVisit.position)
        )
        return list(rows.scalars())


async def report_for(env: Env, visit_id: uuid.UUID) -> VisitReport | None:
    async with env.ctx.sessionmaker() as s:
        return await s.get(VisitReport, visit_id)


async def cycle(env: Env, advance: float = 0) -> dict[str, int]:
    if advance:
        env.clock.advance(seconds=advance)
    return await service.run_call_cycle(env.ctx, clock.now())


async def run_until_dialed(env: Env) -> Call:
    """Espera el lote (20 s) y deja la llamada marcada (``dialing``)."""
    await cycle(env)  # planea (aún dentro de la espera del lote)
    await cycle(env, advance=env.settings.call_batch_wait_seconds + 1)  # planea
    await cycle(env)  # marca
    calls = await all_calls(env)
    assert calls and calls[-1].status == "dialing", [c.status for c in calls]
    return calls[-1]


def webhook_body(
    conversation_id: str,
    call_id: uuid.UUID,
    data: dict[str, Any] | None = None,
    status: str = "done",
) -> dict[str, Any]:
    return {
        "type": "post_call_transcription",
        "event_timestamp": int(clock.now().timestamp()),
        "data": {
            "conversation_id": conversation_id,
            "user_id": str(call_id),
            "status": status,
            "transcript": [
                {"role": "agent", "message": "[happy] Hola, soy UNO.", "time_in_call_secs": 0},
                {"role": "user", "message": "Hola, me fue bien.", "time_in_call_secs": 6},
            ],
            "metadata": {"call_duration_secs": 71, "termination_reason": "end_call tool"},
            "analysis": {
                "data_collection_results": data if data is not None else canned_data(1),
                "transcript_summary": "Resumen.",
            },
        },
    }


async def post_webhook(
    env: Env, body: dict[str, Any], *, secret: str = SECRET, timestamp: int | None = None
) -> httpx.Response:
    raw = json.dumps(body).encode()
    header = sign(secret, raw, timestamp if timestamp is not None else int(clock.now().timestamp()))
    return await env.client.post(
        "/v1/webhooks/elevenlabs",
        content=raw,
        headers={"elevenlabs-signature": header, "content-type": "application/json"},
    )


# ------------------------------------------------------------------ apagado por defecto


async def test_calls_are_off_by_default(env: Env) -> None:
    token = await rep_token(env)
    (visit_id,) = await finish_visits(env, token)
    env.clock.advance(minutes=5)
    assert await service.run_call_cycle(env.ctx, clock.now()) == {}
    assert await all_calls(env) == []
    assert await visit_status(env, visit_id) == "finished"


# ------------------------------------------------------------------ planear


async def test_all_finished_visits_go_in_one_call_in_order(make_env: Any) -> None:
    async with calls_env(make_env, call_max_visits_per_call=5) as env:
        token = await rep_token(env)
        ids = await finish_visits(env, token, 3)
        await run_until_dialed(env)
        calls = await all_calls(env)
        assert len(calls) == 1
        assert await call_visit_ids(env, calls[0].id) == ids
        assert [await visit_status(env, v) for v in ids] == ["in_call"] * 3
        assert len(fake(env).requests) == 1
        assert fake(env).requests[0].dynamic_variables["num_visitas"] == "3"


async def test_it_waits_for_another_visit_after_finish(make_env: Any) -> None:
    async with calls_env(make_env, call_batch_wait_seconds=20) as env:
        token = await rep_token(env)
        await finish_visits(env, token)
        await cycle(env, advance=10)
        assert await all_calls(env) == []  # aún puede llegar «Otro médico aquí»
        await cycle(env, advance=15)
        assert len(await all_calls(env)) == 1


async def test_at_most_five_visits_per_call_and_one_live_call_per_rep(make_env: Any) -> None:
    async with calls_env(make_env, call_max_visits_per_call=5) as env:
        token = await rep_token(env)
        ids = await finish_visits(env, token, 7)
        first = await run_until_dialed(env)
        assert await call_visit_ids(env, first.id) == ids[:5]
        await cycle(env, advance=30)
        assert len(await all_calls(env)) == 1  # no hay una segunda llamada viva
        # La primera termina; entonces salen las dos que faltaban.
        fake(env)._script = lambda req: FakeOutcome(kind="answered")
        await cycle(env, advance=30)
        assert (await all_calls(env))[0].status == "completed"
        await cycle(env, advance=30)  # planea y marca la siguiente
        calls = await all_calls(env)
        assert len(calls) == 2
        assert await call_visit_ids(env, calls[1].id) == ids[5:]


async def test_no_call_while_rep_is_in_another_visit(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        await finish_visits(env, token)
        # Llega a otra visita y sigue en ella.
        d_ev, doctor_id = doctor_event(env, name="Dr. Otro")
        v_ev, other = visit_event(env, doctor_id=doctor_id, scheduled_at=clock.now())
        await post_sync(env, token, [d_ev, v_ev, arrived_event(other, location(4.6765, -74.0481))])
        await cycle(env, advance=60)
        assert await all_calls(env) == []
        env.clock.advance(hours=4)  # se olvidó de tocar «Terminé»: ya no bloquea
        await cycle(env)
        assert len(await all_calls(env)) == 1


@pytest.mark.parametrize(
    ("hour_utc", "expect_call"),
    [
        (11, False),
        (12, True),
        (23, True),
        (23.99, False),
    ],  # Bogotá = UTC−5: 06:00, 07:00, 18:00, 19:00
)
async def test_calls_only_inside_the_window(
    make_env: Any, hour_utc: float, expect_call: bool
) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        await finish_visits(env, token)
        env.clock.set(env.clock.t.replace(hour=int(hour_utc), minute=int((hour_utc % 1) * 60)))
        await cycle(env, advance=60)
        assert bool(await all_calls(env)) is expect_call


async def test_unauthorized_phone_is_never_called_outside_prod(make_env: Any) -> None:
    async with make_env(
        call_backend="elevenlabs",
        elevenlabs_api_key="k",
        elevenlabs_agent_id="agent_x",
        elevenlabs_phone_number_id="phnum_x",
        voice_provider=FakeProvider(),
        call_allowed_phones="+573009999999",
    ) as env:
        token = await rep_token(env)  # su celular no está en la lista
        await finish_visits(env, token)
        await cycle(env, advance=60)
        assert await all_calls(env) == []
        assert fake(env).requests == []


# ------------------------------------------------------------------ resultado


async def test_answered_call_creates_the_report_and_marks_visit_ready(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        call = await run_until_dialed(env)
        await cycle(env, advance=20)  # el proveedor ya tiene el resultado
        assert (await all_calls(env))[0].status == "completed"
        assert await visit_status(env, visit_id) == "ready"

        report = await report_for(env, visit_id)
        assert report is not None and report.status == "ready" and report.complete
        f = report.fields
        assert f["interest_level"]["value"] == 4
        assert f["visit_outcome"]["value"] == "follow_up_set"
        assert f["order_taken"]["value"] is False
        assert f["no_order_reason"]["value"] == "no_need_to_switch"
        assert f["competitor"]["value"] == "pantoprazol"
        assert f["next_action_in_days"]["value"] == 14
        assert (
            f["next_action_due"]["value"]
            == (clock.local_date(clock.now(), "America/Bogota") + timedelta(days=14)).isoformat()
        )
        assert all(entry["source"] == "call" for entry in f.values())

        done = (await all_calls(env))[0]
        assert done.transcript and done.analysis and done.duration_s == 75
        assert call.id == done.id

        # La bitácora de dominio recibe hechos, nunca texto libre ni datos personales.
        async with env.ctx.sessionmaker() as s:
            events = (
                (
                    await s.execute(
                        select(DomainEvent).where(
                            DomainEvent.event_type.in_(
                                ["call_placed", "call_completed", "visit_extracted"]
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert {e.event_type for e in events} == {
            "call_placed",
            "call_completed",
            "visit_extracted",
        }

        def keys(value: Any) -> set[str]:
            if isinstance(value, dict):
                return set(value) | {k for v in value.values() for k in keys(v)}
            return set()

        for event in events:
            assert not keys(event.payload) & FORBIDDEN_KEYS
        extracted = next(e for e in events if e.event_type == "visit_extracted")
        assert "summary" not in extracted.payload and "competitor" not in extracted.payload


async def test_two_visits_two_reports_from_extra_json(make_env: Any) -> None:
    async with calls_env(make_env, call_max_visits_per_call=5) as env:
        token = await rep_token(env)
        ids = await finish_visits(env, token, 2)
        await run_until_dialed(env)
        await cycle(env, advance=20)
        assert [await visit_status(env, v) for v in ids] == ["ready", "ready"]
        first, second = await report_for(env, ids[0]), await report_for(env, ids[1])
        assert first and second
        assert first.fields["interest_level"]["value"] == 4
        assert second.fields["order_taken"]["value"] is True
        assert second.fields["visit_outcome"]["value"] == "order_taken"


async def test_broken_extra_json_keeps_the_first_report(make_env: Any) -> None:
    async with calls_env(make_env, call_max_visits_per_call=5) as env:
        token = await rep_token(env)
        ids = await finish_visits(env, token, 2)
        data = canned_data(2)
        data["extra_visits_json"] = {"value": "{esto no es json"}
        fake(env)._script = lambda req: FakeOutcome(data_collection=data)
        await run_until_dialed(env)
        await cycle(env, advance=20)
        assert await visit_status(env, ids[0]) == "ready"
        assert await visit_status(env, ids[1]) == "finished"  # queda pendiente, no se pierde
        assert await report_for(env, ids[1]) is None


async def test_rep_edits_are_never_overwritten_by_the_call(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        async with env.ctx.sessionmaker() as s:
            now = clock.now()
            s.add(
                VisitReport(
                    visit_id=visit_id,
                    status="ready",
                    fields={
                        "interest_level": {"value": 2, "confidence": "high", "source": "rep_edit"}
                    },
                    created_at=now,
                    updated_at=now,
                )
            )
            await s.commit()
        await run_until_dialed(env)
        await cycle(env, advance=20)
        report = await report_for(env, visit_id)
        assert report is not None
        assert report.fields["interest_level"] == {
            "value": 2,
            "confidence": "high",
            "source": "rep_edit",
        }
        assert report.fields["visit_outcome"]["source"] == "call"


# ------------------------------------------------------------------ reintentos


@pytest.mark.parametrize("kind", ["no_answer", "busy", "voicemail"])
async def test_no_contact_retries_at_5_then_15_minutes_then_fails(make_env: Any, kind: str) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(kind=kind)  # type: ignore[arg-type]
        await run_until_dialed(env)

        # Intento 1 → se detecta el fallo → reintento a +5 min.
        await cycle(env, advance=20)
        call = (await all_calls(env))[0]
        assert call.status == "queued" and call.attempt == 1
        assert call.scheduled_for - clock.now() == timedelta(minutes=5)
        assert await visit_status(env, visit_id) == "finished"

        await cycle(env, advance=4 * 60)  # todavía no toca
        assert (await all_calls(env))[0].attempt == 1
        await cycle(env, advance=61)  # marca de nuevo
        assert (await all_calls(env))[0].attempt == 2
        await cycle(env, advance=20)  # falla otra vez → +15 min
        call = (await all_calls(env))[0]
        assert call.status == "queued" and call.scheduled_for - clock.now() == timedelta(minutes=15)

        await cycle(env, advance=15 * 60 + 1)
        assert (await all_calls(env))[0].attempt == 3
        await cycle(env, advance=20)  # tercera falla → definitiva
        call = (await all_calls(env))[0]
        assert call.status == "failed"
        assert call.failure_reason in {"no-answer", "busy", "voicemail"}
        assert await visit_status(env, visit_id) == "finished"
        async with env.ctx.sessionmaker() as s:
            live = (
                (await s.execute(select(CallVisit).where(CallVisit.live.is_(True)))).scalars().all()
            )
        assert live == []


async def test_a_call_that_never_answers_the_provider_times_out_and_retries(make_env: Any) -> None:
    async with calls_env(make_env, call_result_timeout_minutes=12) as env:
        token = await rep_token(env)
        await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(delay=timedelta(hours=1))
        await run_until_dialed(env)
        await cycle(env, advance=11 * 60)
        assert (await all_calls(env))[0].status == "dialing"
        await cycle(env, advance=90)
        call = (await all_calls(env))[0]
        assert call.status == "queued" and call.failure_reason == "timeout"


async def test_provider_error_at_dial_time_is_retried_or_failed(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        await finish_visits(env, token)
        fake(env).fail_next_dial = ProviderError("proveedor no disponible (503)")
        await cycle(env)
        await cycle(env, advance=21)
        await cycle(env)
        call = (await all_calls(env))[0]
        assert (
            call.status == "queued"
            and call.attempt == 1
            and call.failure_reason == "provider_error"
        )

    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        fake(env).fail_next_dial = ProviderError("número inválido", retryable=False)
        await cycle(env)
        await cycle(env, advance=21)
        await cycle(env)
        assert (await all_calls(env))[0].status == "failed"
        assert await visit_status(env, visit_id) == "finished"


async def test_rep_who_cannot_talk_is_called_back_when_he_asks(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(
            data_collection={
                "callback_in_minutes": {"value": 10},
                "interview_complete": {"value": False},
            }
        )
        await run_until_dialed(env)
        await cycle(env, advance=20)
        call = (await all_calls(env))[0]
        assert call.status == "queued" and call.failure_reason == "incomplete"
        assert call.scheduled_for - clock.now() == timedelta(minutes=10)
        assert await visit_status(env, visit_id) == "finished"
        assert await report_for(env, visit_id) is None


async def test_expired_summary_does_not_trigger_an_evening_closing_call(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(kind="no_answer")
        await run_until_dialed(env)
        for advance in (20, 5 * 60 + 1, 20, 15 * 60 + 1, 20):
            await cycle(env, advance=advance)
        assert (await all_calls(env))[0].status == "failed"

        # Hasta las 18:00 (23:00 UTC) no se vuelve a llamar por esa visita.
        await cycle(env, advance=3600)
        assert len(await all_calls(env)) == 1
        env.clock.set(env.clock.t.replace(hour=23, minute=1))
        await cycle(env)
        await cycle(env)
        calls = await all_calls(env)
        assert len(calls) == 1
        async with env.ctx.sessionmaker() as session:
            visit = await session.get(Visit, visit_id)
            assert visit.report_invalid_at is not None

        # Si esa también falla, esa noche no hay una tercera.
        fake(env)._script = lambda req: FakeOutcome(kind="no_answer")
        for advance in (20, 5 * 60 + 1, 20, 15 * 60 + 1, 20):
            await cycle(env, advance=advance)
        env.clock.set(env.clock.t.replace(hour=23, minute=50))
        await cycle(env)
        assert len(await all_calls(env)) == 1


async def test_deadline_waits_for_notification_even_if_finish_was_yesterday(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        env.clock.advance(hours=23)  # 06:00 en Bogotá: dentro de las 24 h y fuera de horario
        await cycle(env)
        assert await visit_status(env, visit_id) == "finished"
        env.clock.advance(hours=2)  # ya pasaron más de 24 h desde el «Terminé»
        await cycle(env)
        assert await visit_status(env, visit_id) == "in_call"
        async with env.ctx.sessionmaker() as session:
            visit = await session.get(Visit, visit_id)
            assert visit.report_notified_at == clock.now()
            assert visit.report_due_at == clock.now() + timedelta(minutes=30)
            assert visit.report_invalid_at is None


# ------------------------------------------------------------------ webhook


async def dialing_call(env: Env, token: str) -> tuple[Call, uuid.UUID]:
    (visit_id,) = await finish_visits(env, token)
    fake(env)._script = lambda req: FakeOutcome(delay=timedelta(hours=1))
    call = await run_until_dialed(env)
    assert call.provider_conversation_id
    return call, visit_id


async def test_webhook_completes_the_call_once(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        call, visit_id = await dialing_call(env, token)
        body = webhook_body(call.provider_conversation_id or "", call.id)
        first = await post_webhook(env, body)
        assert first.status_code == 200 and first.json()["outcome"] == "completed"
        assert await visit_status(env, visit_id) == "ready"
        report = await report_for(env, visit_id)
        assert report is not None
        stamp = report.updated_at

        again = await post_webhook(env, body)  # ElevenLabs reintenta: no duplica nada
        assert again.status_code == 200 and again.json()["outcome"] == "stale"
        report = await report_for(env, visit_id)
        assert report is not None and report.updated_at == stamp
        transcript = (await all_calls(env))[0].transcript or []
        assert transcript[0]["text"] == "Hola, soy UNO."  # sin la etiqueta [happy]


async def test_webhook_finds_the_call_by_user_id_when_conversation_id_is_unknown(
    make_env: Any,
) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        call, visit_id = await dialing_call(env, token)
        r = await post_webhook(env, webhook_body("otra-conversacion", call.id))
        assert r.json()["outcome"] == "stale"  # conversación distinta a la marcada: se ignora
        assert await visit_status(env, visit_id) == "in_call"


@pytest.mark.parametrize("problem", ["bad_secret", "stale", "no_header", "no_secret_configured"])
async def test_webhook_rejects_bad_signatures(make_env: Any, problem: str) -> None:
    overrides: dict[str, Any] = (
        {"elevenlabs_webhook_secret": ""} if problem == "no_secret_configured" else {}
    )
    async with make_env(
        call_backend="fake", **({"elevenlabs_webhook_secret": SECRET} | overrides)
    ) as env:
        token = await rep_token(env)
        call, visit_id = await dialing_call(env, token)
        body = webhook_body(call.provider_conversation_id or "", call.id)
        raw = json.dumps(body).encode()
        headers = {"content-type": "application/json"}
        now = int(clock.now().timestamp())
        if problem == "bad_secret":
            headers["elevenlabs-signature"] = sign("otro-secreto", raw, now)
        elif problem == "stale":
            headers["elevenlabs-signature"] = sign(SECRET, raw, now - 31 * 60)
        elif problem in ("no_secret_configured",):
            headers["elevenlabs-signature"] = sign(SECRET, raw, now)
        r = await env.client.post("/v1/webhooks/elevenlabs", content=raw, headers=headers)
        assert r.status_code == 401
        assert await visit_status(env, visit_id) == "in_call"


async def test_webhook_with_tampered_body_is_rejected(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        call, _ = await dialing_call(env, token)
        raw = json.dumps(webhook_body(call.provider_conversation_id or "", call.id)).encode()
        header = sign(SECRET, raw, int(clock.now().timestamp()))
        r = await env.client.post(
            "/v1/webhooks/elevenlabs",
            content=raw.replace(b"71", b"99"),
            headers={"elevenlabs-signature": header, "content-type": "application/json"},
        )
        assert r.status_code == 401


async def test_call_initiation_failure_webhook_schedules_the_retry(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        call, visit_id = await dialing_call(env, token)
        body = {
            "type": "call_initiation_failure",
            "data": {
                "conversation_id": call.provider_conversation_id,
                "failure_reason": "no-answer",
                "metadata": {"type": "sip"},
            },
        }
        r = await post_webhook(env, body)
        assert r.status_code == 200 and r.json()["outcome"] == "retry"
        current = (await all_calls(env))[0]
        assert current.status == "queued" and current.failure_reason == "no-answer"
        assert await visit_status(env, visit_id) == "finished"


async def test_webhook_for_unknown_conversation_is_accepted_without_effect(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        r = await post_webhook(env, webhook_body("desconocida", uuid.uuid4()))
        assert r.status_code == 200 and r.json()["outcome"] == "unknown"


async def test_audio_webhook_is_accepted_and_ignored(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        r = await post_webhook(env, {"type": "post_call_audio", "data": {"conversation_id": "x"}})
        assert r.status_code == 200 and r.json()["outcome"] == "ignored"


# ------------------------------------------------------------------ proveedor real (HTTP simulado)


def eleven(handler: Any) -> ElevenLabsProvider:
    client = httpx.AsyncClient(
        base_url="https://api.elevenlabs.io",
        headers={"xi-api-key": "k"},
        transport=httpx.MockTransport(handler),
    )
    return ElevenLabsProvider(
        api_key="k",
        agent_id="agent_1",
        phone_number_id="phnum_1",
        channel="sip_trunk",
        client=client,
    )


async def test_elevenlabs_outbound_request_shape() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"success": True, "conversation_id": "conv_9", "sip_call_id": "sip_9"}
        )

    provider = eleven(handler)
    from uno.modules.calls.provider import DialRequest

    call_id = uuid.uuid4()
    dialed = await provider.place_call(
        DialRequest(call_id, "+573001112233", {"visitador_nombre": "Ana"})
    )
    assert (dialed.conversation_id, dialed.provider_call_id) == ("conv_9", "sip_9")
    assert seen["path"] == "/v1/convai/sip-trunk/outbound-call"
    assert seen["body"] == {
        "agent_id": "agent_1",
        "agent_phone_number_id": "phnum_1",
        "to_number": "+573001112233",
        "conversation_initiation_client_data": {
            "dynamic_variables": {"visitador_nombre": "Ana"},
            "user_id": str(call_id),
        },
    }


@pytest.mark.parametrize(
    ("status", "retryable"), [(500, True), (503, True), (429, True), (400, False), (422, False)]
)
async def test_elevenlabs_errors_are_classified(status: int, retryable: bool) -> None:
    from uno.modules.calls.provider import DialRequest

    provider = eleven(lambda request: httpx.Response(status, json={"detail": "x"}))
    with pytest.raises(ProviderError) as info:
        await provider.place_call(DialRequest(uuid.uuid4(), "+573001112233", {}))
    assert info.value.retryable is retryable


async def test_elevenlabs_network_failure_is_retryable() -> None:
    from uno.modules.calls.provider import DialRequest

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    with pytest.raises(ProviderError) as info:
        await eleven(boom).place_call(DialRequest(uuid.uuid4(), "+573001112233", {}))
    assert info.value.retryable


def test_parse_conversation_reads_the_real_shape() -> None:
    result = parse_conversation(
        {
            "conversation_id": "c1",
            "status": "done",
            "transcript": [
                {
                    "role": "agent",
                    "message": "[happy] Hola",
                    "time_in_call_secs": 0,
                    "tool_calls": [],
                },
                {"role": "user", "message": "  Bien  ", "time_in_call_secs": 4},
                {
                    "role": "agent",
                    "message": None,
                    "tool_calls": [{"tool_name": "voicemail_detection"}],
                },
            ],
            "metadata": {"call_duration_secs": 33, "termination_reason": "x"},
            "analysis": {
                "data_collection_results": {"v1_interest_level": {"value": 3}},
                "transcript_summary": "s",
            },
        }
    )
    assert result.status == "done" and result.user_turns == 1 and result.voicemail
    assert result.turns[0].text == "Hola" and result.duration_s == 33
    assert result.data_collection["v1_interest_level"]["value"] == 3
    assert parse_conversation({"status": "processing"}).status == "pending"
    assert parse_conversation({"status": "failed"}).status == "failed"


# ------------------------------------------------------------------ varios trabajadores


async def test_two_workers_never_call_the_same_visit_twice(make_env: Any) -> None:
    import asyncio

    async with calls_env(make_env) as env:
        token = await rep_token(env)
        await finish_visits(env, token, 2)
        env.clock.advance(seconds=30)
        await asyncio.gather(*(service.plan_calls(env.ctx, clock.now()) for _ in range(4)))
        calls = await all_calls(env)
        assert len(calls) == 1
        await asyncio.gather(*(service.place_due_calls(env.ctx, clock.now()) for _ in range(4)))
        assert len(fake(env).requests) == 1  # una sola marcación


async def test_inactive_rep_gets_no_call(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        await finish_visits(env, token)
        await make_user(env, phone="+573007778899", name="Otro")  # no interfiere
        async with env.ctx.sessionmaker() as s:
            from uno.modules.auth.models import User

            user = (await s.execute(select(User).where(User.phone_e164 == REP_PHONE))).scalar_one()
            user.is_active = False
            await s.commit()
        await cycle(env, advance=60)
        assert await all_calls(env) == []


_ = datetime  # (import usado en anotaciones de pruebas futuras)


# ------------------------------------------------------------------ desvío de pruebas (solo desarrollo)


async def test_phone_override_sends_the_call_to_the_tester_not_the_rep(make_env: Any) -> None:
    async with calls_env(make_env, call_phone_override="+573004198710") as env:
        token = await rep_token(env)
        await finish_visits(env, token)
        await run_until_dialed(env)
        assert [r.to_phone for r in fake(env).requests] == ["+573004198710"]


async def test_the_allowlist_checks_the_number_that_will_actually_ring(make_env: Any) -> None:
    def build(allowed: str) -> Any:
        return make_env(
            call_backend="elevenlabs",
            elevenlabs_api_key="k",
            elevenlabs_agent_id="agent_x",
            elevenlabs_phone_number_id="phnum_x",
            voice_provider=FakeProvider(),
            call_phone_override="+573004198710",
            call_allowed_phones=allowed,
        )

    async with build("+573004198710") as env:  # el celular de prueba SÍ está autorizado
        token = await rep_token(env)
        await finish_visits(env, token)
        await run_until_dialed(env)
        assert fake(env).requests[0].to_phone == "+573004198710"

    async with build(
        REP_PHONE
    ) as env:  # autorizado el del visitador, pero suena el de prueba: no sale
        token = await rep_token(env)
        await finish_visits(env, token)
        await cycle(env, advance=60)
        assert fake(env).requests == [] and await all_calls(env) == []


def test_the_phone_override_is_forbidden_in_production() -> None:
    from uno.config import Settings

    with pytest.raises(ValueError, match="OVERRIDE"):
        Settings(
            env="prod",
            jwt_secret="x" * 40,
            cookie_secure=True,
            call_phone_override="+573004198710",
        )


# ------------------------------------------------------------------ Twilio (canal detectado)


def eleven_auto(handler: Any) -> ElevenLabsProvider:
    client = httpx.AsyncClient(
        base_url="https://api.elevenlabs.io",
        headers={"xi-api-key": "k"},
        transport=httpx.MockTransport(handler),
    )
    return ElevenLabsProvider(
        api_key="k", agent_id="agent_1", phone_number_id="phnum_1", client=client
    )


async def test_a_twilio_number_is_detected_and_uses_the_twilio_endpoint() -> None:
    from uno.modules.calls.provider import DialRequest

    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"provider": "twilio", "phone_number": "+15707769534"})
        assert json.loads(request.content)["agent_phone_number_id"] == "phnum_1"
        return httpx.Response(
            200, json={"success": True, "conversation_id": "c1", "callSid": "CA9"}
        )

    provider = eleven_auto(handler)
    request = DialRequest(uuid.uuid4(), "+573004198710", {"visitador_nombre": "Ana"})
    dialed = await provider.place_call(request)
    assert (dialed.conversation_id, dialed.provider_call_id) == ("c1", "CA9")
    await provider.place_call(request)  # el canal se recuerda: no se vuelve a consultar
    assert seen == [
        ("GET", "/v1/convai/phone-numbers/phnum_1"),
        ("POST", "/v1/convai/twilio/outbound-call"),
        ("POST", "/v1/convai/twilio/outbound-call"),
    ]


async def test_a_sip_trunk_number_still_uses_the_sip_endpoint() -> None:
    from uno.modules.calls.provider import DialRequest

    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(200, json={"provider": "sip_trunk"})
        return httpx.Response(
            200, json={"success": True, "conversation_id": "c", "sip_call_id": "s"}
        )

    dialed = await eleven_auto(handler).place_call(DialRequest(uuid.uuid4(), "+573004198710", {}))
    assert dialed.provider_call_id == "s"
    assert paths[-1] == "/v1/convai/sip-trunk/outbound-call"


async def test_a_missing_number_is_a_permanent_error_and_a_network_error_is_retryable() -> None:
    from uno.modules.calls.provider import DialRequest

    gone = eleven_auto(lambda r: httpx.Response(404, json={"detail": "x"}))
    with pytest.raises(ProviderError) as info:
        await gone.place_call(DialRequest(uuid.uuid4(), "+573004198710", {}))
    assert info.value.retryable is False

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    with pytest.raises(ProviderError) as info2:
        await eleven_auto(boom).place_call(DialRequest(uuid.uuid4(), "+573004198710", {}))
    assert info2.value.retryable is True
