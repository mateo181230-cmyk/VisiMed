"""Entrenar por la API: consentimiento, formulario, práctica, transcripción, evaluación y gerencia.

Con el proveedor simulado (``FakeProvider``): no se crea nada en Tavus ni se gastan minutos.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from copy import deepcopy
from datetime import timedelta
from typing import Any

import pytest_asyncio
from sqlalchemy import func, select

from uno.events import DomainEvent
from uno.modules.training.content import load_catalog
from uno.modules.training.models import PracticeAttempt, PracticeEvaluation, PracticeTurn
from uno.modules.training.provider import FakeProvider, ProviderError
from uno.modules.training.service import run_training_cycle

from .conftest import ADMIN_PHONE, Env, bearer, login, make_user, rep_token

GENERAL = "medico_general_indiferenciado"
ALL_OK = {
    "l1_apertura": "b",
    "l1_profundiza": "b",
    "l1_parafraseo": "b",
    "l1_cierre": "b",
}


@pytest_asyncio.fixture
async def fake(make_env) -> AsyncIterator[tuple[Env, FakeProvider]]:  # type: ignore[no-untyped-def]
    provider = FakeProvider()
    async with make_env(
        conversation_provider=provider,
        training_backend="fake",
        tavus_callback_base_url="https://api.test",
    ) as env:
        yield env, provider


async def accept(env: Env, token: str, salutation: str = "doctora") -> dict[str, Any]:
    r = await env.client.put(
        "/v1/training/profile",
        headers=bearer(token),
        json={"salutation": salutation, "accept_consent": True},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def start(env: Env, token: str, slug: str = GENERAL, expect: int = 201) -> dict[str, Any]:
    r = await env.client.post(
        "/v1/training/attempts", headers=bearer(token), json={"scenario_slug": slug}
    )
    assert r.status_code == expect, r.text
    return r.json()


async def end(env: Env, token: str, attempt_id: str) -> dict[str, Any]:
    r = await env.client.post(f"/v1/training/attempts/{attempt_id}/end", headers=bearer(token))
    assert r.status_code == 200, r.text
    return r.json()


async def test_legacy_basic_evaluation_gets_flags_without_rewriting_scores(
    fake: tuple[Env, FakeProvider],
) -> None:
    env, _provider = fake
    token = await rep_token(env)
    await accept(env, token)
    attempt = await start(env, token)
    await end(env, token, attempt["id"])
    attempt_id = uuid.UUID(attempt["id"])
    async with env.ctx.sessionmaker() as session:
        stored = (
            await session.execute(
                select(PracticeEvaluation).where(PracticeEvaluation.attempt_id == attempt_id)
            )
        ).scalar_one()
        legacy = deepcopy(stored.result)
        for competency in legacy["competencies"]:
            competency.pop("evaluated", None)
        stored.result = legacy
        original_total = stored.total
        await session.commit()

    response = await env.client.get(f"/v1/training/attempts/{attempt_id}", headers=bearer(token))
    assert response.status_code == 200
    result = response.json()["evaluation"]
    assert result["total"] == original_total
    assert {c["id"] for c in result["competencies"] if c["evaluated"]} == {
        "apertura",
        "argumentacion",
        "cierre",
    }
    async with env.ctx.sessionmaker() as session:
        stored = (
            await session.execute(
                select(PracticeEvaluation).where(PracticeEvaluation.attempt_id == attempt_id)
            )
        ).scalar_one()
        assert stored.result == legacy


# ------------------------------------------------------------------ sin médico


async def test_overview_without_doctor_still_offers_preparation(env: Env) -> None:
    token = await rep_token(env)
    r = await env.client.get("/v1/training/overview", headers=bearer(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["doctor"]["status"] == "off"
    assert "preparación" in body["doctor"]["message"]
    assert [s["slug"] for s in body["scenarios"]][0] == GENERAL
    assert body["suggested_slug"] == GENERAL
    assert all(s["progress"]["status"] == "sin_practicar" for s in body["scenarios"])
    assert body["profile"]["consent_accepted"] is False

    await accept(env, token)
    r = await env.client.post(
        "/v1/training/attempts", headers=bearer(token), json={"scenario_slug": GENERAL}
    )
    assert r.status_code == 503 and r.json()["detail"]["code"] == "doctor_unavailable"


async def test_scenario_detail_hides_the_correct_answers(env: Env) -> None:
    token = await rep_token(env)
    r = await env.client.get(f"/v1/training/scenarios/{GENERAL}", headers=bearer(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["doctor_name"] == "Dr. Andrés Gómez"
    scenario = load_catalog().get(GENERAL)
    assert scenario is not None
    assert len(body["quiz"]) == len(scenario.quiz) == 4
    assert len(body["lesson"]["blocks"]) == len(scenario.lesson.blocks)
    # El formulario no trae la respuesta: ninguna clave de preguntas u opciones la delata.
    # (Se revisan claves, no textos: una opción puede decir «correcta».)
    keys = {k for q in body["quiz"] for k in q} | {
        k for q in body["quiz"] for o in q["options"] for k in o
    }
    assert not any("correct" in k for k in keys)
    r = await env.client.get("/v1/training/scenarios/no-existe", headers=bearer(token))
    assert r.status_code == 404


async def test_quiz_is_graded_explained_and_stored_per_rep(env: Env) -> None:
    token = await rep_token(env)
    r = await env.client.post(
        f"/v1/training/scenarios/{GENERAL}/quiz",
        headers=bearer(token),
        json={"answers": {"l1_apertura": "b"}},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "quiz_incomplete"

    answers = {**ALL_OK, "l1_cierre": "a"}
    r = await env.client.post(
        f"/v1/training/scenarios/{GENERAL}/quiz", headers=bearer(token), json={"answers": answers}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["correct"], body["total"], body["passed"]) == (3, 4, True)
    wrong = next(x for x in body["results"] if not x["is_correct"])
    assert wrong["question_id"] == "l1_cierre" and wrong["correct_option"] == "b"
    assert wrong["explanation"] and wrong["source"]

    overview = (await env.client.get("/v1/training/overview", headers=bearer(token))).json()
    assert overview["scenarios"][0]["quiz"] == {"correct": 3, "total": 4}
    other = await rep_token(env, phone="+573004445566", name="Otro Rep")
    theirs = (await env.client.get("/v1/training/overview", headers=bearer(other))).json()
    assert theirs["scenarios"][0]["quiz"] is None  # cada visitador ve lo suyo


# ------------------------------------------------------------------ práctica completa


async def test_full_practice_cycle_with_the_simulated_doctor(
    fake: tuple[Env, FakeProvider],
) -> None:
    env, provider = fake
    token = await rep_token(env, name="Ana María Pérez")

    r = await env.client.post(
        "/v1/training/attempts", headers=bearer(token), json={"scenario_slug": GENERAL}
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "consent_required"

    await accept(env, token, "doctora")
    await env.client.post(
        f"/v1/training/scenarios/{GENERAL}/quiz", headers=bearer(token), json={"answers": ALL_OK}
    )
    attempt = await start(env, token)
    assert attempt["status"] == "live"
    assert attempt["conversation_url"].startswith("fake:")
    assert attempt["greeting"] == "Buenos días, doctora. Qué gusto saludarle, cuénteme."
    assert attempt["max_seconds"] == 300

    request = provider.requests[-1]
    assert "Ana" in request.context and "Pérez" not in request.context  # solo el nombre de pila
    assert "+57" not in request.context
    assert request.callback_url and request.callback_url.startswith(
        "https://api.test/v1/webhooks/tavus/"
    )

    again = await start(env, token, expect=409)
    assert again["detail"]["code"] == "attempt_active"

    done = await end(env, token, attempt["id"])
    assert done["status"] == "evaluated"
    evaluation = done["evaluation"]
    assert evaluation["total"] == 28 and evaluation["preliminary"] is True
    assert evaluation["training"]["approved"] is True
    assert evaluation["training"]["diagnosis"].startswith("Dominio demostrado")
    assert evaluation["best_response"]["id"]
    assert done["delta"] is None
    assert len(done["transcript"]) == 10 and done["transcript"][0]["role"] == "doctor"

    overview = (await env.client.get("/v1/training/overview", headers=bearer(token))).json()
    first = overview["scenarios"][0]
    assert first["progress"]["status"] == "aprobado" and first["progress"]["best"] == 28
    assert overview["suggested_slug"] == "gastroenterologo_esceptico"  # siguiente en la ruta

    second = await start(env, token)
    assert second["greeting"] == "Hola, bienvenido. Lo escucho con gusto."  # rota entre intentos
    done2 = await end(env, token, second["id"])
    assert done2["delta"] == 0

    async with env.ctx.sessionmaker() as session:
        kinds = (await session.execute(select(DomainEvent.event_type, DomainEvent.payload))).all()
    evaluated = [p for k, p in kinds if k == "practice_attempt_evaluated"]
    assert len(evaluated) == 2 and evaluated[0]["total"] == 28
    assert all("transcript" not in str(p) for _, p in kinds)


async def test_provider_without_credits_blocks_for_a_while(fake: tuple[Env, FakeProvider]) -> None:
    env, provider = fake
    token = await rep_token(env)
    await accept(env, token)
    provider.fail_next = ProviderError("no_credits", "sin créditos")
    r = await env.client.post(
        "/v1/training/attempts", headers=bearer(token), json={"scenario_slug": GENERAL}
    )
    assert r.status_code == 503 and r.json()["detail"]["code"] == "doctor_unavailable"
    assert "más tarde" in r.json()["detail"]["message"]

    overview = (await env.client.get("/v1/training/overview", headers=bearer(token))).json()
    assert overview["doctor"]["status"] == "unavailable"
    assert overview["active_attempt_id"] is None  # el intento fallido no queda vivo

    env.clock.advance(minutes=6)
    overview = (await env.client.get("/v1/training/overview", headers=bearer(token))).json()
    assert overview["doctor"]["status"] == "available"
    assert (await start(env, token))["status"] == "live"


async def test_opening_entrenar_asks_the_provider_at_most_every_few_minutes(
    fake: tuple[Env, FakeProvider],
) -> None:
    env, provider = fake
    token = await rep_token(env)
    provider.probe_result = "no_credits"
    overview = (await env.client.get("/v1/training/overview", headers=bearer(token))).json()
    assert overview["doctor"]["status"] == "unavailable"
    assert overview["doctor"]["code"] == "no_credits"
    assert "formulario" in overview["doctor"]["message"]  # qué puede hacer mientras tanto
    r = await env.client.get(f"/v1/training/scenarios/{GENERAL}", headers=bearer(token))
    assert r.json()["doctor"]["status"] == "unavailable"
    assert provider.probes == 1  # una sola consulta para las dos pantallas

    await accept(env, token)
    await start(env, token, expect=503)
    assert provider.requests == []  # ni se intenta crear la conversación

    provider.probe_result = None  # se recargaron los créditos
    env.clock.advance(minutes=6)
    overview = (await env.client.get("/v1/training/overview", headers=bearer(token))).json()
    assert overview["doctor"]["status"] == "available" and provider.probes == 2
    assert (await start(env, token))["status"] == "live"


async def test_daily_limit(make_env) -> None:  # type: ignore[no-untyped-def]
    async with make_env(
        conversation_provider=FakeProvider(), training_backend="fake", training_attempts_per_day=1
    ) as env:
        token = await rep_token(env)
        await accept(env, token)
        attempt = await start(env, token)
        await end(env, token, attempt["id"])
        blocked = await start(env, token, expect=429)
        assert blocked["detail"]["code"] == "daily_limit"


# ------------------------------------------------------------------ webhook de Tavus


async def test_webhook_is_authenticated_by_token_and_idempotent(
    fake: tuple[Env, FakeProvider],
) -> None:
    env, provider = fake
    token = await rep_token(env)
    await accept(env, token)
    attempt = await start(env, token)
    url = provider.requests[-1].callback_url
    assert url is not None
    path = url.removeprefix("https://api.test")
    conversation_id = attempt["conversation_url"].removeprefix("fake:")
    body = {
        "conversation_id": conversation_id,
        "event_type": "application.transcription_ready",
        "properties": {
            "transcript": [
                {"role": "system", "content": "instrucciones"},
                {"role": "assistant", "content": "Sí, cuénteme."},
                {
                    "role": "user",
                    "content": "Doctor, ESOMED es excelente y se absorbe más del 95%.",
                },
                {"role": "assistant", "content": "¿Eso con qué lo sustenta?"},
            ]
        },
    }
    assert (await env.client.post("/v1/webhooks/tavus/otro-token", json=body)).status_code == 404
    wrong = {**body, "conversation_id": "c_ajena"}
    assert (await env.client.post(path, json=wrong)).status_code == 404

    first = await env.client.post(path, json=body)
    assert first.status_code == 200 and first.json()["outcome"] == "evaluated"
    again = await env.client.post(path, json=body)
    assert again.json()["outcome"] == "already"

    view = (
        await env.client.get(f"/v1/training/attempts/{attempt['id']}", headers=bearer(token))
    ).json()
    assert view["status"] == "evaluated"
    ids = [e["id"] for e in view["evaluation"]["critical_errors"]]
    # Nivel básico: exagerar sigue siendo error crítico; explorar todavía no se exige.
    assert "exagera_beneficios" in ids and "promociona_sin_explorar" not in ids
    assert "95%" in view["evaluation"]["key_moment"]["quote"]
    async with env.ctx.sessionmaker() as session:
        turns = (await session.execute(select(func.count()).select_from(PracticeTurn))).scalar_one()
    assert turns == 3  # «system» no es parte de la conversación


# ------------------------------------------------------------------ trabajador


async def test_worker_closes_forgotten_visits_and_gives_up_without_transcript(
    fake: tuple[Env, FakeProvider],
) -> None:
    env, provider = fake
    token = await rep_token(env)
    await accept(env, token)
    attempt = await start(env, token)

    env.clock.advance(seconds=300 + 121)  # duración máxima + margen: el visitador cerró la app
    stats = await run_training_cycle(env.ctx, env.clock.now())
    assert stats.get("timed_out") == 1 and stats.get("evaluated") == 1
    view = (
        await env.client.get(f"/v1/training/attempts/{attempt['id']}", headers=bearer(token))
    ).json()
    assert view["status"] == "evaluated"

    provider.transcript_ready = False
    attempt2 = await start(env, token)
    ended = await end(env, token, attempt2["id"])
    assert ended["status"] == "ended"
    env.clock.advance(minutes=6)
    await run_training_cycle(env.ctx, env.clock.now())
    async with env.ctx.sessionmaker() as session:
        row = await session.get(PracticeAttempt, uuid.UUID(attempt2["id"]))
        assert row is not None and row.status == "no_transcript"


# ------------------------------------------------------------------ gerencia


async def test_manager_sees_progress_per_rep_and_scenario(fake: tuple[Env, FakeProvider]) -> None:
    env, _ = fake
    token = await rep_token(env, name="Ana Rep")
    await accept(env, token)
    attempt = await start(env, token)
    await end(env, token, attempt["id"])

    assert (await env.client.get("/v1/manager/training", headers=bearer(token))).status_code == 403
    await make_user(env, phone=ADMIN_PHONE, role="admin", name="Gerente")
    admin = await login(env, ADMIN_PHONE)
    r = await env.client.get("/v1/manager/training", headers=bearer(admin))
    assert r.status_code == 200, r.text
    rows = r.json()
    ana = next(row for row in rows if row["full_name"] == "Ana Rep")
    general = ana["scenarios"][0]
    assert general["status"] == "aprobado" and general["attempts"] == 1
    assert general["first"] == general["best"] == 28 and general["compliance_errors"] == 0
    assert all(s["status"] == "sin_practicar" for s in ana["scenarios"][1:])


async def test_shutdown_event_ends_a_live_visit(fake: tuple[Env, FakeProvider]) -> None:
    env, provider = fake
    token = await rep_token(env)
    await accept(env, token)
    attempt = await start(env, token)
    path = (provider.requests[-1].callback_url or "").removeprefix("https://api.test")
    body = {
        "conversation_id": attempt["conversation_url"].removeprefix("fake:"),
        "event_type": "system.shutdown",
        "properties": {"shutdown_reason": "participant_left_timeout reached"},
    }
    assert (await env.client.post(path, json=body)).json()["outcome"] == "ended"
    async with env.ctx.sessionmaker() as session:
        row = (await session.execute(select(PracticeAttempt))).scalar_one()
        assert row.status == "ended" and row.end_reason == "participant_left_timeout reached"
        assert row.ended_at is not None and row.ended_at - row.created_at < timedelta(minutes=1)
