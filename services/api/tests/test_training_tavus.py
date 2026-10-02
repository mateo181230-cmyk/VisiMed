"""Entrenar: cliente de Tavus (sin red, con ``httpx.MockTransport``) y publicación de PAL."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from uno import clock
from uno.config import Settings
from uno.modules.training import pal
from uno.modules.training.content import load_catalog
from uno.modules.training.models import PracticeAttempt, TrainingScenarioVersion
from uno.modules.training.provider import (
    PAL_PREFIX,
    ConversationRequest,
    ProviderError,
    TavusProvider,
    transcript_from_conversation,
)

from .conftest import Env, make_user


class FakeTavus:
    """Tavus en memoria: registra lo que recibe y responde como la API real."""

    def __init__(self, *, pal_id_prefix: str = "") -> None:
        self.pal_id_prefix = pal_id_prefix
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.pals: dict[str, dict[str, Any]] = {
            "p_ajeno": {"pal_id": "p_ajeno", "pal_name": "Feria Jetour · Gloria"},
        }
        self.conversation_status = 200
        self.delete_status = 204

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        path = request.url.path
        if request.method == "POST" and path == "/v2/conversations":
            if self.conversation_status != 200:
                return httpx.Response(
                    self.conversation_status, json={"message": "The user is out of credits."}
                )
            return httpx.Response(
                200,
                json={"conversation_id": "c123", "conversation_url": "https://tavus.daily.co/c123"},
            )
        if request.method == "POST" and path == "/v2/pals":
            pal_id = f"{self.pal_id_prefix}p{len(self.pals)}"
            # Como la API real: quita puntos, guiones y paréntesis del nombre («Dr.» → «Dr»).
            name = re.sub(r"[.()\-]", "", body["pal_name"])  # type: ignore[index]
            self.pals[pal_id] = {"pal_id": pal_id, "pal_name": name}
            return httpx.Response(200, json={"pal_id": pal_id})
        if request.method == "GET" and path == "/v2/pals":
            return httpx.Response(200, json={"data": list(self.pals.values())})
        if path.startswith("/v2/pals/"):
            pal_id = path.rsplit("/", 1)[1]
            if pal_id not in self.pals:
                return httpx.Response(404, json={"message": "not found"})
            if request.method == "GET":
                return httpx.Response(200, json=self.pals[pal_id])
            if request.method == "DELETE":
                if self.delete_status != 204:
                    return httpx.Response(self.delete_status, json={"message": "temporary failure"})
                del self.pals[pal_id]
                return httpx.Response(204)
        if request.method == "GET" and path == "/v2/conversations/c123":
            return httpx.Response(
                200,
                json={
                    "status": "ended",
                    "events": [
                        {"event_type": "system.replica_joined", "properties": {}},
                        {
                            "event_type": "application.transcription_ready",
                            "properties": {
                                "transcript": [
                                    {"role": "system", "content": "prompt"},
                                    {"role": "assistant", "content": "Tengo tres minutos."},
                                    {
                                        "role": "user",
                                        "content": "Doctor, ¿cómo define hoy qué IBP usar?",
                                        "seconds_from_start": 4.5,
                                        "duration": 3.1,
                                    },
                                ]
                            },
                        },
                    ],
                },
            )
        if request.method == "POST" and path == "/v2/conversations/c123/end":
            return httpx.Response(200, json={})
        if request.method == "DELETE" and path == "/v2/conversations/c123":
            return httpx.Response(204)
        return httpx.Response(418, json={"message": f"ruta no simulada {path}"})

    def provider(self) -> TavusProvider:
        client = httpx.AsyncClient(
            base_url="https://tavusapi.com", transport=httpx.MockTransport(self.handler)
        )
        return TavusProvider(api_key="k", client=client)


def request(**overrides: Any) -> ConversationRequest:
    values: dict[str, Any] = {
        "pal_id": "p1",
        "name": "UNO Entrenar a1",
        "context": "La persona se llama Ana.",
        "greeting": "Tengo tres minutos. ¿De qué se trata?",
        "callback_url": None,
        "max_seconds": 300,
        "audio_only": False,
        "scenario_slug": "gastroenterologo_esceptico",
    }
    values.update(overrides)
    return ConversationRequest(**values)


async def test_create_conversation_sends_the_attempt_and_nothing_else() -> None:
    tavus = FakeTavus()
    created = await tavus.provider().create_conversation(request())
    assert created.conversation_id == "c123"
    method, path, body = tavus.calls[-1]
    assert (method, path) == ("POST", "/v2/conversations")
    assert body is not None
    assert body["pal_id"] == "p1"
    assert body["custom_greeting"] == "Tengo tres minutos. ¿De qué se trata?"
    assert body["conversational_context"] == "La persona se llama Ana."
    assert body["properties"]["max_call_duration"] == 300
    assert body["properties"]["languages"] == ["es"]
    assert "callback_url" not in body  # sin URL pública, la transcripción se consulta

    await tavus.provider().create_conversation(
        request(callback_url="https://api/x", audio_only=True)
    )
    body = tavus.calls[-1][2]
    assert body is not None and body["callback_url"] == "https://api/x" and body["audio_only"]


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (402, "no_credits", False),
        (401, "auth", False),
        (429, "busy", True),
        (503, "unavailable", True),
    ],
)
async def test_errors_become_stable_codes(status: int, code: str, retryable: bool) -> None:
    tavus = FakeTavus()
    tavus.conversation_status = status
    with pytest.raises(ProviderError) as info:
        await tavus.provider().create_conversation(request())
    assert info.value.code == code and info.value.retryable is retryable


async def test_unpublished_scenario_never_calls_tavus() -> None:
    tavus = FakeTavus()
    with pytest.raises(ProviderError) as info:
        await tavus.provider().create_conversation(request(pal_id=None))
    assert info.value.code == "not_published" and tavus.calls == []


async def test_probe_is_free_and_leaves_nothing_behind() -> None:
    tavus = FakeTavus()
    assert await tavus.provider().probe("p1") is None
    method, path, body = tavus.calls[0]
    assert (method, path) == ("POST", "/v2/conversations")
    assert body is not None and body["test_mode"] is True and body["pal_id"] == "p1"
    assert tavus.calls[-1][:2] == ("DELETE", "/v2/conversations/c123")  # se borra la de prueba

    tavus = FakeTavus()
    tavus.conversation_status = 402
    assert await tavus.provider().probe("p1") == "no_credits"
    assert [c[:2] for c in tavus.calls] == [("POST", "/v2/conversations")]
    assert await FakeTavus().provider().probe() == "not_published"  # la cuenta no tiene PAL propios


async def test_transcript_is_read_from_the_verbose_conversation() -> None:
    transcript = await FakeTavus().provider().fetch_transcript("c123")
    assert transcript.ready and transcript.ended
    assert [(t.role, t.text) for t in transcript.turns] == [
        ("doctor", "Tengo tres minutos."),
        ("rep", "Doctor, ¿cómo define hoy qué IBP usar?"),
    ]
    assert transcript.turns[1].t == 4.5
    pending = transcript_from_conversation({"status": "active", "events": []})
    assert not pending.ready and not pending.ended


async def test_shared_account_pals_from_other_projects_are_never_touched() -> None:
    tavus = FakeTavus()
    provider = tavus.provider()
    with pytest.raises(ProviderError):
        await provider.create_pal({"pal_name": "Otro proyecto"})
    with pytest.raises(ProviderError):
        await provider.delete_pal("p_ajeno")
    assert "p_ajeno" in tavus.pals
    own = await provider.create_pal({"pal_name": f"{PAL_PREFIX} · prueba"})
    assert await provider.delete_pal(own) is True


def test_pal_payload_uses_the_elevenlabs_voice_and_the_compiled_prompt() -> None:
    catalog = load_catalog()
    scenario = catalog.get("internista_exigente")
    assert scenario is not None
    settings = Settings(env="test", database_url="sqlite+aiosqlite:///:memory:")
    payload = pal.build_pal(catalog, scenario, settings, 3)
    digest = catalog.content_hash(scenario)[:8]
    assert payload["pal_name"] == f"{PAL_PREFIX} · ESOMED · Dra. Carolina Peña · v3 · {digest}"
    assert payload["default_face_id"] == scenario.casting.face_id
    assert payload["languages"] == ["es"]
    tts = payload["layers"]["tts"]
    assert tts["tts_engine"] == "elevenlabs"
    assert tts["external_voice_id"] == scenario.casting.voice_id
    assert tts["tts_model_name"] == "eleven_turbo_v2_5"
    assert "api_key" not in tts  # voz pública: no se entrega la llave de ElevenLabs
    assert payload["layers"]["perception"]["perception_model"] == "off"
    assert payload["layers"]["llm"]["model"] == "tavus-gemma-4"
    flow = payload["layers"]["conversational_flow"]
    assert (flow["turn_taking_patience"], flow["pal_interruptibility"]) == ("medium", "low")
    assert "Dra. Carolina Peña" in payload["system_prompt"]

    with_key = Settings(
        env="test", database_url="sqlite+aiosqlite:///:memory:", training_tts_api_key="sk_x"
    )
    assert pal.build_pal(catalog, scenario, with_key, 1)["layers"]["tts"]["api_key"] == "sk_x"


async def test_apply_publishes_once_and_is_idempotent(make_env) -> None:  # type: ignore[no-untyped-def]
    tavus = FakeTavus()
    async with make_env(conversation_provider=tavus.provider()) as env:
        env: Env
        first = await pal.apply(env.ctx, say=lambda _: None)
        assert all(v.startswith("publicado v1") for v in first.values()), first
        second = await pal.apply(env.ctx, say=lambda _: None)
        assert all(v.startswith("igual") for v in second.values()), second
        created = [c for c in tavus.calls if c[:2] == ("POST", "/v2/pals")]
        assert len(created) == 4  # uno por escenario, una sola vez
        async with env.ctx.sessionmaker() as session:
            versions = (await session.execute(select(TrainingScenarioVersion))).scalars().all()
        assert {v.scenario_slug for v in versions} == {s.slug for s in load_catalog().scenarios}
        assert all(v.tavus_pal_id and v.retired_at is None for v in versions)
        assert "p_ajeno" in tavus.pals

    # Otra base de datos publica el mismo contenido: reutiliza los PAL, no crea duplicados.
    async with make_env(conversation_provider=tavus.provider()) as other:
        again = await pal.apply(other.ctx, say=lambda _: None)
        assert all(v.startswith("reutilizado v1") for v in again.values()), again
        assert len([c for c in tavus.calls if c[:2] == ("POST", "/v2/pals")]) == 4


async def test_apply_republishes_when_the_api_key_belongs_to_another_account(make_env) -> None:  # type: ignore[no-untyped-def]
    original = FakeTavus()
    replacement = FakeTavus(pal_id_prefix="new_account_")
    async with make_env(conversation_provider=original.provider()) as env:
        env: Env
        await pal.apply(env.ctx, say=lambda _: None)
        original_ids = set(original.pals)

        env.ctx.conversation_provider = replacement.provider()
        outcome = await pal.apply(env.ctx, say=lambda _: None)
        assert all(v.startswith("publicado v2") for v in outcome.values()), outcome
        async with env.ctx.sessionmaker() as session:
            versions = (await session.execute(select(TrainingScenarioVersion))).scalars().all()
        retired = [v for v in versions if v.retired_at is not None]
        current = [v for v in versions if v.retired_at is None]
        assert len(retired) == len(current) == 4
        assert all(v.version == 1 and v.tavus_pal_id in original_ids for v in retired)
        assert all(v.version == 2 and v.tavus_pal_id in replacement.pals for v in current)
        assert all(v.tavus_pal_id not in original_ids for v in current)
        assert set(original.pals) == original_ids  # no borra médicos de la cuenta anterior

        again = await pal.apply(env.ctx, say=lambda _: None)
        assert all(v.startswith("igual") for v in again.values()), again
        assert len([c for c in replacement.calls if c[:2] == ("POST", "/v2/pals")]) == 4
        assert "p_ajeno" in replacement.pals


def scenario_version(pal_id: str, version: int, *, retired: bool) -> TrainingScenarioVersion:
    return TrainingScenarioVersion(
        scenario_slug="gastroenterologo_esceptico",
        version=version,
        content_hash="a" * 64,
        prompt_version="v2",
        tavus_pal_id=pal_id,
        face_id="face",
        voice_id="voice",
        published_at=clock.now(),
        retired_at=clock.now() if retired else None,
    )


async def test_cleanup_preserves_a_retired_pal_reused_by_a_current_version(make_env: Any) -> None:
    tavus = FakeTavus()
    provider = tavus.provider()
    async with make_env(conversation_provider=provider) as env:
        pal_id = await provider.create_pal({"pal_name": f"{PAL_PREFIX} · compartido"})
        async with env.ctx.sessionmaker() as session:
            session.add_all(
                [
                    scenario_version(pal_id, 1, retired=True),
                    scenario_version(pal_id, 2, retired=False),
                ]
            )
            await session.commit()
        assert await pal.cleanup(env.ctx, say=lambda _: None) == 0
        assert pal_id in tavus.pals
        assert not [call for call in tavus.calls if call[0] == "DELETE"]
        async with env.ctx.sessionmaker() as session:
            versions = (await session.scalars(select(TrainingScenarioVersion))).all()
            assert all(version.tavus_pal_id == pal_id for version in versions)


@pytest.mark.parametrize("status", ["starting", "live"])
async def test_cleanup_preserves_a_pal_used_by_any_retired_version_attempt(
    make_env: Any, status: str
) -> None:
    tavus = FakeTavus()
    provider = tavus.provider()
    async with make_env(conversation_provider=provider) as env:
        user_id = await make_user(env)
        pal_id = await provider.create_pal({"pal_name": f"{PAL_PREFIX} · compartido"})
        async with env.ctx.sessionmaker() as session:
            first = scenario_version(pal_id, 1, retired=True)
            second = scenario_version(pal_id, 2, retired=True)
            session.add_all([first, second])
            await session.flush()
            session.add(
                PracticeAttempt(
                    user_id=user_id,
                    scenario_slug=second.scenario_slug,
                    version_id=second.id,
                    content_hash=second.content_hash,
                    status=status,
                    provider="tavus",
                    created_at=clock.now(),
                )
            )
            await session.commit()
        assert await pal.cleanup(env.ctx, say=lambda _: None) == 0
        assert pal_id in tavus.pals
        assert not [call for call in tavus.calls if call[0] == "DELETE"]


async def test_cleanup_deletes_an_unused_shared_pal_once_and_clears_all_references(
    make_env: Any,
) -> None:
    tavus = FakeTavus()
    provider = tavus.provider()
    async with make_env(conversation_provider=provider) as env:
        pal_id = await provider.create_pal({"pal_name": f"{PAL_PREFIX} · compartido"})
        async with env.ctx.sessionmaker() as session:
            session.add_all(
                [
                    scenario_version(pal_id, 1, retired=True),
                    scenario_version(pal_id, 2, retired=True),
                ]
            )
            await session.commit()
        assert await pal.cleanup(env.ctx, say=lambda _: None) == 1
        assert pal_id not in tavus.pals and "p_ajeno" in tavus.pals
        assert len([call for call in tavus.calls if call[0] == "DELETE"]) == 1
        async with env.ctx.sessionmaker() as session:
            versions = (await session.scalars(select(TrainingScenarioVersion))).all()
            assert all(version.tavus_pal_id is None for version in versions)
        assert await pal.cleanup(env.ctx, say=lambda _: None) == 0


async def test_cleanup_keeps_references_after_remote_delete_failure_for_retry(
    make_env: Any,
) -> None:
    tavus = FakeTavus()
    provider = tavus.provider()
    async with make_env(conversation_provider=provider) as env:
        pal_id = await provider.create_pal({"pal_name": f"{PAL_PREFIX} · retirar"})
        async with env.ctx.sessionmaker() as session:
            session.add(scenario_version(pal_id, 1, retired=True))
            await session.commit()
        tavus.delete_status = 503
        assert await pal.cleanup(env.ctx, say=lambda _: None) == 0
        async with env.ctx.sessionmaker() as session:
            stored_id = await session.scalar(select(TrainingScenarioVersion.tavus_pal_id))
            assert stored_id == pal_id
        assert pal_id in tavus.pals
        tavus.delete_status = 204
        assert await pal.cleanup(env.ctx, say=lambda _: None) == 1
        assert pal_id not in tavus.pals
