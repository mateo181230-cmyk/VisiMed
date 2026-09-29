"""La ficha en el celular: bajada de estado, confirmar y corregir un campo."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from uno.events import DomainEvent
from uno.modules.calls.models import VisitReport
from uno.modules.calls.provider import FakeOutcome

from .conftest import Env, rep_token
from .helpers import ev, get_state, post_sync
from .test_calls import calls_env, cycle, fake, finish_visits, run_until_dialed, visit_status


async def with_report(env: Env) -> tuple[str, uuid.UUID]:
    """Un visitador con una visita ya llamada y con su ficha lista."""
    token = await rep_token(env)
    (visit_id,) = await finish_visits(env, token)
    await run_until_dialed(env)
    await cycle(env, advance=20)
    assert await visit_status(env, visit_id) == "ready"
    return token, visit_id


def confirm(visit_id: uuid.UUID, **kw: Any) -> dict[str, Any]:
    return ev("report_confirmed", {}, visit_id=visit_id, **kw)


def edit(visit_id: uuid.UUID, field: str, value: Any, **kw: Any) -> dict[str, Any]:
    return ev("report_field_edited", {"field": field, "value": value}, visit_id=visit_id, **kw)


async def report(env: Env, visit_id: uuid.UUID) -> VisitReport:
    async with env.ctx.sessionmaker() as s:
        row = await s.get(VisitReport, visit_id)
    assert row is not None
    return row


async def test_state_delivers_the_report_and_the_ready_status(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token, visit_id = await with_report(env)
        state = await get_state(env, token)
        (r,) = state["reports"]
        assert r["visit_id"] == str(visit_id) and r["status"] == "ready" and r["complete"]
        assert r["fields"]["interest_level"] == {
            "value": 4,
            "confidence": "high",
            "source": "call",
        }
        assert r["fields"]["order_taken"]["value"] is False  # «no hubo pedido» es un dato
        assert "objection" not in r["fields"]  # vacío = ausente
        visit = next(v for v in state["visits"] if v["id"] == str(visit_id))
        assert visit["status"] == "ready" and visit["call"] is None  # la llamada ya terminó


async def test_reports_come_incrementally_with_the_cursor(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token, visit_id = await with_report(env)
        first = await get_state(env, token)
        again = await get_state(env, token, first["cursor"])
        assert again["reports"] == []
        await post_sync(env, token, [confirm(visit_id)])
        delta = await get_state(env, token, first["cursor"])
        assert [x["status"] for x in delta["reports"]] == ["confirmed"]


async def test_a_pending_retry_is_visible_to_the_phone(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(kind="no_answer")
        await run_until_dialed(env)
        await cycle(env, advance=20)
        state = await get_state(env, token)
        visit = next(v for v in state["visits"] if v["id"] == str(visit_id))
        assert visit["status"] == "finished"
        assert visit["call"]["status"] == "queued" and visit["call"]["attempt"] == 1
        assert visit["call"]["reason"] == "no-answer" and visit["call"]["next_at"]


async def test_confirm_marks_report_and_visit_and_is_idempotent(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token, visit_id = await with_report(env)
        body = await post_sync(env, token, [confirm(visit_id)])
        assert body["results"][0]["status"] == "applied"
        row = await report(env, visit_id)
        assert row.status == "confirmed" and row.confirmed_at is not None
        assert await visit_status(env, visit_id) == "confirmed"
        stamp = row.confirmed_at
        again = await post_sync(env, token, [confirm(visit_id)])  # otro event_id, mismo hecho
        assert again["results"][0]["status"] == "applied"
        assert (await report(env, visit_id)).confirmed_at == stamp


async def test_edit_marks_the_field_as_the_reps_and_survives_a_new_call(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token, visit_id = await with_report(env)
        body = await post_sync(
            env,
            token,
            [
                edit(visit_id, "interest_level", 2),
                edit(visit_id, "objection", "  Dice que es caro  "),
                edit(visit_id, "no_order_reason", "price"),
            ],
        )
        assert [r["status"] for r in body["results"]] == ["applied"] * 3
        f = (await report(env, visit_id)).fields
        assert f["interest_level"] == {"value": 2, "confidence": "high", "source": "rep_edit"}
        assert f["objection"]["value"] == "Dice que es caro"
        assert f["no_order_reason"]["value"] == "price"
        assert f["competitor"]["source"] == "call"  # lo no corregido sigue siendo de la llamada
        state = await get_state(env, token)
        assert state["reports"][0]["fields"]["interest_level"]["source"] == "rep_edit"


async def test_clearing_a_field_removes_it_from_the_card(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token, visit_id = await with_report(env)
        await post_sync(env, token, [edit(visit_id, "competitor", "")])
        assert (await report(env, visit_id)).fields["competitor"]["value"] is None
        state = await get_state(env, token)
        assert "competitor" not in state["reports"][0]["fields"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("interest_level", 9),
        ("interest_level", "mucho"),
        ("visit_outcome", "compró_todo"),
        ("no_order_reason", 3),
    ],
)
async def test_invalid_edits_are_rejected_without_touching_the_card(
    make_env: Any, field: str, value: Any
) -> None:
    async with calls_env(make_env) as env:
        token, visit_id = await with_report(env)
        before = (await report(env, visit_id)).fields
        body = await post_sync(env, token, [edit(visit_id, field, value)])
        assert body["results"][0]["status"] == "rejected"
        assert (await report(env, visit_id)).fields == before


async def test_derived_fields_cannot_be_edited(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token, visit_id = await with_report(env)
        body = await post_sync(env, token, [edit(visit_id, "next_action_due", "2026-01-01")])
        assert body["results"][0]["status"] == "rejected"  # fuera de los campos editables


async def test_no_report_no_confirm(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        body = await post_sync(env, token, [confirm(visit_id)])
        assert body["results"][0]["status"] == "rejected"
        assert body["results"][0]["reason"] == "no_report"


async def test_a_rep_cannot_touch_someone_elses_report(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        _, visit_id = await with_report(env)
        other = await rep_token(env, phone="+573007770001", name="Otra")
        body = await post_sync(env, other, [confirm(visit_id), edit(visit_id, "interest_level", 1)])
        assert [r["reason"] for r in body["results"]] == ["unknown_visit", "unknown_visit"]
        assert (await report(env, visit_id)).status == "ready"
        assert (await get_state(env, other))["reports"] == []


async def test_edits_after_confirming_are_allowed_and_keep_it_confirmed(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token, visit_id = await with_report(env)
        await post_sync(env, token, [confirm(visit_id)])
        await post_sync(env, token, [edit(visit_id, "commitment", "Recetar en 3 pacientes")])
        row = await report(env, visit_id)
        assert row.status == "confirmed" and row.fields["commitment"]["source"] == "rep_edit"


async def test_domain_events_never_carry_the_typed_text(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token, visit_id = await with_report(env)
        await post_sync(
            env, token, [edit(visit_id, "objection", "Texto libre con Juan Pérez"), confirm(visit_id)]
        )
        async with env.ctx.sessionmaker() as s:
            rows = (
                (
                    await s.execute(
                        select(DomainEvent).where(
                            DomainEvent.event_type.in_(["report_edited", "report_confirmed"])
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert {r.event_type for r in rows} == {"report_edited", "report_confirmed"}
        assert "Juan" not in str([r.payload for r in rows])
        edited = next(r for r in rows if r.event_type == "report_edited")
        assert edited.payload["field"] == "objection" and edited.payload["cleared"] is False
