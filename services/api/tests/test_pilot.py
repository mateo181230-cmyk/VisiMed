"""El ciclo exigido por el piloto, incluyendo confirmación y aislamiento de datos."""

from __future__ import annotations

from typing import Any

import pytest

from uno import clock
from uno.modules.calls.provider import FakeOutcome, Turn, canned_data
from uno.modules.calls.schema import parse_analysis

from .conftest import login, make_user, rep_token
from .helpers import get_state, post_sync
from .test_calls import (
    call_visit_ids,
    calls_env,
    cycle,
    fake,
    finish_visits,
    report_for,
    run_until_dialed,
    visit_status,
)
from .test_reports import edit


def confirmed_data() -> dict[str, Any]:
    return canned_data() | {"v1_report_confirmed": {"value": True}}


async def test_default_is_one_call_per_visit(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        visits = await finish_visits(env, token, 2)
        call = await run_until_dialed(env)
        assert await call_visit_ids(env, call.id) == visits[:1]
        assert await visit_status(env, visits[1]) == "finished"
        assert fake(env).requests[0].dynamic_variables["fecha_actual"] == "2026-09-29"


async def test_voice_confirmation_saves_full_report_and_audit(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(
            data_collection=confirmed_data(),
            turns=[
                Turn("user", "Presenté ESOMED. Receptividad cuatro. Llevaré muestras."),
                Turn(
                    "agent",
                    "El resumen es: ESOMED, muestras en dos semanas. ¿Confirmas este resumen de la visita?",
                ),
                Turn("user", "Sí, correcto."),
            ],
        )
        await run_until_dialed(env)
        await cycle(env, advance=20)
        report = await report_for(env, visit_id)
        assert report and report.status == "confirmed" and report.confirmed_at and report.complete
        assert report.extractor_version == "elevenlabs-v2"
        assert report.fields["receptiveness_score"]["value"] == 4
        assert report.fields["visit_objective"]["value"]
        assert report.fields["new_information"]["value"]
        assert await visit_status(env, visit_id) == "confirmed"
        state = await get_state(env, token)
        assert state["reports"][0]["status"] == "confirmed"


@pytest.mark.parametrize(
    "turns",
    [
        [Turn("agent", "¿Hubo pedido?"), Turn("user", "Sí, correcto")],
        [
            Turn("agent", "¿Confirmas este resumen de la visita?"),
            Turn("user", "No, fue en otra clínica"),
        ],
        [Turn("user", "Hola"), Turn("agent", "¿Confirmas este resumen de la visita?")],
        [
            Turn("agent", "¿Confirmas este resumen de la visita?"),
            Turn("user", "Sí, pero la fecha es otra"),
        ],
    ],
)
async def test_an_extractor_flag_without_readback_acceptance_does_not_confirm(
    make_env: Any,
    turns: list[Turn],
) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(data_collection=confirmed_data(), turns=turns)
        await run_until_dialed(env)
        await cycle(env, advance=20)
        report = await report_for(env, visit_id)
        assert report and report.status == "ready" and report.confirmed_at is None


async def test_revised_readback_and_concrete_date_win(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        data = confirmed_data()
        data["v1_details_json"]["value"]["next_action_date"] = "2026-10-09"
        fake(env)._script = lambda req: FakeOutcome(
            data_collection=data,
            turns=[
                Turn("agent", "El resumen dice muestras en dos semanas. ¿Confirmas este resumen?"),
                Turn("user", "No, el nueve de octubre"),
                Turn(
                    "agent",
                    "Resumen corregido: muestras el nueve de octubre. ¿Confirmas este resumen de la visita?",
                ),
                Turn("user", "Sí, correcto"),
            ],
        )
        await run_until_dialed(env)
        await cycle(env, advance=20)
        report = await report_for(env, visit_id)
        assert report and report.status == "confirmed"
        assert report.fields["next_action_due"]["value"] == "2026-10-09"
        await post_sync(env, token, [edit(visit_id, "next_action_date", "2026-10-20")])
        report = await report_for(env, visit_id)
        assert report and report.fields["next_action_due"]["value"] == "2026-10-20"
        assert report.fields["next_action_in_days"]["value"] is None
        assert report.fields["next_action_due"]["source"] == "rep_edit"


async def test_callback_with_default_flags_never_creates_a_report(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(
            data_collection={
                "v1_order_taken": {"value": False},
                "v1_samples_delivered": {"value": False},
                "callback_in_minutes": {"value": 30},
                "v1_report_confirmed": {"value": False},
            },
            turns=[Turn("user", "No puedo hablar ahora, en media hora")],
        )
        await run_until_dialed(env)
        await cycle(env, advance=20)
        assert await report_for(env, visit_id) is None
        assert await visit_status(env, visit_id) == "finished"
        visit = (await get_state(env, token))["visits"][0]
        # Media hora desde la respuesta superaría el plazo original: no se reprograma.
        assert visit["call"] is None and visit["report_due_at"]


async def test_queued_retry_waits_if_rep_started_another_visit(make_env: Any) -> None:
    from .helpers import arrived_event, doctor_event, location, visit_event

    async with calls_env(make_env) as env:
        token = await rep_token(env)
        await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(kind="no_answer")
        await run_until_dialed(env)
        await cycle(env, advance=20)
        d, doctor_id = doctor_event(env, name="Dr. Otro")
        v, other = visit_event(env, doctor_id=doctor_id, scheduled_at=clock.now())
        await post_sync(env, token, [d, v, arrived_event(other, location(4.67, -74.04))])
        await cycle(env, advance=301)
        assert len(fake(env).requests) == 1


async def test_snapshot_scopes_rep_and_gives_manager_real_history(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        await run_until_dialed(env)
        await cycle(env, advance=20)
        other = await rep_token(env, phone="+573007770001", name="Otro")
        await finish_visits(env, other)
        response = await env.client.get(
            "/v1/intelligence/snapshot", headers={"authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        body = response.json()
        assert [v["id"] for v in body["visits"]] == [str(visit_id)]
        assert len(body["reports"]) == 1 and len(body["doctors"]) == 1
        assert body["esomed_connected"] is False
        assert "arrival_lat" not in body["visits"][0] and "transcript" not in str(body)
        await make_user(env, phone="+573007770002", name="Gerencia", role="manager")
        manager_token = await login(env, phone="+573007770002")
        team = await env.client.get(
            "/v1/intelligence/snapshot", headers={"authorization": f"Bearer {manager_token}"}
        )
        assert team.status_code == 200 and len(team.json()["visits"]) == 2
        # Después de 8 días el historial conserva la visita aunque no entre en la agenda de 7 días.
        env.clock.advance(days=8)
        history = await env.client.get(
            "/v1/intelligence/snapshot", headers={"authorization": f"Bearer {token}"}
        )
        # El token venció: la API exige renovar sesión incluso para el historial.
        assert history.status_code == 401
        token = await login(env)
        history = await env.client.get(
            "/v1/intelligence/snapshot", headers={"authorization": f"Bearer {token}"}
        )
        assert history.status_code == 200 and history.json()["reports"][0]["visit_id"] == str(
            visit_id
        )
        agenda = await get_state(env, token)
        assert agenda["reports"] == []  # fuera de la ventana de agenda, presente en el historial


async def test_presented_products_change_the_line_and_edits_refresh_it(make_env: Any) -> None:
    from uno.ids import uuid7
    from uno.modules.catalog.models import Product

    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)  # agenda: GASTRU
        async with env.ctx.sessionmaker() as session:
            session.add(
                Product(id=uuid7(), name="Producto respiratorio", line_id=env.lines["RESPI"])
            )
            await session.commit()
        fake(env)._script = lambda req: FakeOutcome(
            data_collection=canned_data()
            | {"v1_products_discussed": {"value": "Producto respiratorio"}}
        )
        await run_until_dialed(env)
        await cycle(env, advance=20)

        async def line_ids() -> list[str]:
            response = await env.client.get(
                "/v1/intelligence/snapshot", headers={"authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            visit = response.json()["visits"][0]
            assert visit["primary_line_id"] == str(env.lines["GASTRU"])
            return visit["discussed_line_ids"]

        assert await line_ids() == [str(env.lines["RESPI"])]
        await post_sync(env, token, [edit(visit_id, "products_discussed", "OSTRU")])
        assert await line_ids() == [str(env.lines["OSTRU"])]
        await post_sync(env, token, [edit(visit_id, "products_discussed", "Producto sin catálogo")])
        assert await line_ids() == []  # no atribuirlo a la línea planeada


async def test_legacy_complete_flag_does_not_hide_missing_pilot_fields(make_env: Any) -> None:
    from uno.modules.calls.models import VisitReport

    from .test_reports import confirm

    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        await run_until_dialed(env)
        await cycle(env, advance=20)
        async with env.ctx.sessionmaker() as session:
            report = await session.get(VisitReport, visit_id)
            assert report
            report.fields = {k: v for k, v in report.fields.items() if k != "visit_objective"}
            report.complete = True  # una versión anterior consideraba suficientes otros campos
            await session.commit()
        state = await get_state(env, token)
        assert state["reports"][0]["complete"] is False
        response = await env.client.get(
            "/v1/intelligence/snapshot", headers={"authorization": f"Bearer {token}"}
        )
        assert response.json()["reports"][0]["complete"] is False
        await post_sync(env, token, [confirm(visit_id)])
        report = await report_for(env, visit_id)
        assert report and report.status == "confirmed" and report.complete is False


@pytest.mark.parametrize("bad", ["{broken", "[]", "42"])
def test_broken_details_keep_core_and_flag_incomplete(bad: str) -> None:
    data = canned_data() | {"v1_details_json": {"value": bad}}
    (report,) = parse_analysis(data, 1)
    assert report.fields["products_discussed"].value == "ESOMED"
    assert not report.complete and "details_json" in report.problems


@pytest.mark.parametrize("bad", [4.8, 9, "mucho", True])
def test_receptivity_is_never_inferred_or_truncated(bad: Any) -> None:
    data = canned_data()
    data["v1_details_json"]["value"]["receptiveness_score"] = bad
    (report,) = parse_analysis(data, 1)
    assert "receptiveness_score" not in report.fields and not report.complete


def test_interest_does_not_replace_receptivity_and_uncertain_essential_is_incomplete() -> None:
    data = canned_data()
    data["v1_details_json"]["value"].pop("receptiveness_score")
    (report,) = parse_analysis(data, 1)
    assert "interest_level" in report.fields and not report.complete
    data = canned_data() | {"uncertain_fields": {"value": "v1_visit_objective"}}
    (report,) = parse_analysis(data, 1)
    assert report.fields["visit_objective"].confidence == "low" and not report.complete


def test_explicit_negative_is_distinct_from_not_asked() -> None:
    data = canned_data()
    data["v1_objection"] = {"value": "No hubo objeciones"}
    (report,) = parse_analysis(data, 1)
    assert report.fields["objection"].value == "No hubo objeciones"
    assert "doctor_disinterest" in report.fields
    assert "next_action_date" not in report.fields


def test_nested_uncertain_detail_from_provider_cannot_be_reported_as_complete() -> None:
    data = canned_data() | {"uncertain_fields": {"value": "v1_details_json.visit_objective"}}
    (report,) = parse_analysis(data, 1)
    assert report.fields["visit_objective"].confidence == "low"
    assert not report.complete


@pytest.mark.parametrize("field", ["commitment", "next_action"])
def test_missing_commitments_or_next_steps_are_incomplete_even_if_provider_says_complete(
    field: str,
) -> None:
    data = canned_data()
    data[f"v1_{field}"] = {"value": ""}
    (report,) = parse_analysis(data, 1)
    assert not report.complete
