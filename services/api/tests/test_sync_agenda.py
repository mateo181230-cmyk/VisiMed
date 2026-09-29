"""Agenda y sincronización idempotente (doc 02: T1.4, T1.5, T3.x)."""

from __future__ import annotations

import asyncio
import random
import uuid
from datetime import timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from uno import clock
from uno.events import DomainEvent
from uno.ids import uuid7
from uno.modules.agenda.models import Visit
from uno.modules.sync import service as sync_service
from uno.modules.sync.models import SyncEvent

from .conftest import OTHER_PHONE, Env, bearer, rep_token
from .helpers import doctor_event, ev, get_state, post_sync, visit_event


def at(env: Env, **delta: float):  # type: ignore[no-untyped-def]
    return clock.now() + timedelta(**delta)


async def count(env: Env, model) -> int:  # type: ignore[no-untyped-def]
    async with env.ctx.sessionmaker() as s:
        return int((await s.execute(select(func.count()).select_from(model))).scalar_one())


async def test_schedule_a_visit_end_to_end(env: Env) -> None:
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    v_ev, visit_id = visit_event(env, doctor_id=doctor_id, scheduled_at=at(env, hours=3))
    out = await post_sync(env, token, [d_ev, v_ev])
    assert [r["status"] for r in out["results"]] == ["applied", "applied"]

    state = await get_state(env, token)
    assert state["full"] is True
    assert [d["full_name"] for d in state["doctors"]] == ["Dra. Laura Méndez"]
    assert state["doctors"][0]["review_state"] == "pending_review"
    assert state["doctors"][0]["default_line_id"] == str(env.lines["GASTRU"])
    assert [i["name"] for i in state["institutions"]] == ["Clínica Central"]
    (visit,) = state["visits"]
    assert visit["id"] == str(visit_id)
    assert visit["status"] == "scheduled"
    assert visit["primary_line_id"] == str(env.lines["GASTRU"])
    assert visit["line_ids"] == [str(env.lines["GASTRU"])]
    assert {x["code"] for x in state["lines"]} == {"RESPI", "OSTRU", "GASTRU"}


async def test_same_batch_three_times_creates_one_visit(env: Env) -> None:
    """T1.4 CA1: reenviar el mismo lote no duplica nada."""
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    v_ev, _ = visit_event(env, doctor_id=doctor_id, scheduled_at=at(env, hours=3))
    first = await post_sync(env, token, [d_ev, v_ev])
    second = await post_sync(env, token, [d_ev, v_ev])
    third = await post_sync(env, token, [d_ev, v_ev])
    assert [r["status"] for r in first["results"]] == ["applied", "applied"]
    assert [r["status"] for r in second["results"]] == ["duplicate", "duplicate"]
    assert [r["status"] for r in third["results"]] == ["duplicate", "duplicate"]
    assert await count(env, Visit) == 1
    assert await count(env, SyncEvent) == 2
    assert await count(env, DomainEvent) == 2  # doctor_created + visit_scheduled


async def test_out_of_order_batch_is_applied_by_device_ts(env: Env) -> None:
    """T1.4 CA2: llegan desordenados y el resultado es el mismo."""
    token = await rep_token(env)
    t0 = clock.now()
    d_ev, doctor_id = doctor_event(env, ts=t0)
    v_ev, _ = visit_event(
        env, doctor_id=doctor_id, scheduled_at=at(env, hours=2), ts=t0 + timedelta(seconds=5)
    )
    out = await post_sync(env, token, [v_ev, d_ev])  # la visita llega antes que el médico
    assert [r["status"] for r in out["results"]] == [
        "applied",
        "applied",
    ]  # orden de respuesta = orden de envío
    assert len((await get_state(env, token))["visits"]) == 1


async def test_invalid_event_in_the_middle_does_not_stop_the_batch(env: Env) -> None:
    """T1.4 CA3."""
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    bad, _ = visit_event(
        env, doctor_id=uuid7(), scheduled_at=at(env, hours=1)
    )  # médico inexistente
    good, _ = visit_event(env, doctor_id=doctor_id, scheduled_at=at(env, hours=2))
    out = await post_sync(env, token, [d_ev, bad, good])
    assert [r["status"] for r in out["results"]] == ["applied", "rejected", "applied"]
    assert out["results"][1]["reason"] == "unknown_doctor"
    assert len((await get_state(env, token))["visits"]) == 1


async def test_rejected_event_stays_rejected_on_resend(env: Env) -> None:
    token = await rep_token(env)
    bad, _ = visit_event(env, doctor_id=uuid7(), scheduled_at=at(env, hours=1))
    first = await post_sync(env, token, [bad])
    second = await post_sync(env, token, [bad])
    assert first["results"][0] == second["results"][0]
    assert second["results"][0]["status"] == "rejected"


async def test_validation_rejections(env: Env) -> None:
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    await post_sync(env, token, [d_ev])
    when = at(env, hours=1)

    unknown_line = ev(
        "visit_scheduled",
        {"doctor_id": str(doctor_id), "line_ids": [str(uuid7())], "scheduled_at": when.isoformat()},
        visit_id=uuid7(),
    )
    no_visit_id = ev(
        "visit_scheduled",
        {
            "doctor_id": str(doctor_id),
            "line_ids": [str(env.lines["GASTRU"])],
            "scheduled_at": when.isoformat(),
        },
    )
    naive_time = ev(
        "visit_scheduled",
        {
            "doctor_id": str(doctor_id),
            "line_ids": [str(env.lines["GASTRU"])],
            "scheduled_at": "2026-10-01T10:00:00",
        },
        visit_id=uuid7(),
    )
    absurd = visit_event(env, doctor_id=doctor_id, scheduled_at=at(env, days=5000))[0]
    dup_line = ev(
        "visit_scheduled",
        {
            "doctor_id": str(doctor_id),
            "line_ids": [str(env.lines["GASTRU"])] * 2,
            "scheduled_at": when.isoformat(),
        },
        visit_id=uuid7(),
    )
    unknown_type = ev("visit_teleported", {}, visit_id=uuid7())
    out = await post_sync(
        env, token, [unknown_line, no_visit_id, naive_time, absurd, dup_line, unknown_type]
    )
    reasons = [r["reason"] for r in out["results"]]
    assert reasons == [
        "unknown_line",
        "visit_id_required",
        "invalid_payload",
        "invalid_time",
        "duplicate_line",
        "unknown_event_type",
    ]


async def test_two_lines_on_one_visit(env: Env) -> None:
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    v_ev, _ = visit_event(
        env, doctor_id=doctor_id, scheduled_at=at(env, hours=2), extra_lines=["RESPI"]
    )
    await post_sync(env, token, [d_ev, v_ev])
    (visit,) = (await get_state(env, token))["visits"]
    assert visit["line_ids"] == [str(env.lines["GASTRU"]), str(env.lines["RESPI"])]
    assert visit["primary_line_id"] == str(env.lines["GASTRU"])


async def test_reschedule_and_not_done_state_machine(env: Env) -> None:
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    v_ev, visit_id = visit_event(env, doctor_id=doctor_id, scheduled_at=at(env, hours=2))
    await post_sync(env, token, [d_ev, v_ev])

    new_time = at(env, hours=5)
    resched = ev("visit_rescheduled", {"scheduled_at": new_time.isoformat()}, visit_id=visit_id)
    out = await post_sync(env, token, [resched])
    assert out["results"][0]["status"] == "applied"
    (visit,) = (await get_state(env, token))["visits"]
    assert visit["scheduled_at"].startswith(
        new_time.astimezone(clock.tz("UTC")).strftime("%Y-%m-%dT%H:%M")
    )

    not_done = ev("visit_not_done", {"reason": "doctor_unavailable"}, visit_id=visit_id)
    assert (await post_sync(env, token, [not_done]))["results"][0]["status"] == "applied"
    (visit,) = (await get_state(env, token))["visits"]
    assert visit["status"] == "not_done"
    assert visit["not_done_reason"] == "doctor_unavailable"

    # Una visita no realizada ya no se reprograma ni cambia de motivo; el mismo motivo es idempotente.
    again = ev(
        "visit_rescheduled", {"scheduled_at": at(env, hours=9).isoformat()}, visit_id=visit_id
    )
    other = ev("visit_not_done", {"reason": "other"}, visit_id=visit_id)
    same = ev("visit_not_done", {"reason": "doctor_unavailable"}, visit_id=visit_id)
    out = await post_sync(env, token, [again, other, same])
    assert [(r["status"], r["reason"]) for r in out["results"]] == [
        ("rejected", "visit_not_editable"),
        ("rejected", "visit_not_editable"),
        ("applied", None),
    ]


async def test_cannot_touch_someone_elses_visit_or_reuse_their_ids(env: Env) -> None:
    ana = await rep_token(env, name="Ana")
    bob = await rep_token(env, phone=OTHER_PHONE, name="Bob")
    d_ev, doctor_id = doctor_event(env)
    v_ev, visit_id = visit_event(env, doctor_id=doctor_id, scheduled_at=at(env, hours=2))
    await post_sync(env, ana, [d_ev, v_ev])

    steal = ev("visit_not_done", {"reason": "other"}, visit_id=visit_id)
    out = await post_sync(env, bob, [steal])
    assert out["results"][0]["reason"] == "unknown_visit"

    # Bob no puede agendar con el médico de Ana (no está en su panel).
    v2, _ = visit_event(env, doctor_id=doctor_id, scheduled_at=at(env, hours=3))
    assert (await post_sync(env, bob, [v2]))["results"][0]["reason"] == "unknown_doctor"

    # Ni reutilizar el event_id de Ana.
    replay = dict(steal, event_id=v_ev["event_id"])
    assert (await post_sync(env, bob, [replay]))["results"][0]["reason"] == "event_id_conflict"

    # El estado de Bob no contiene nada de Ana.
    state = await get_state(env, bob)
    assert state["visits"] == [] and state["doctors"] == []


async def test_visit_id_conflict_and_idempotent_resend_with_new_event_id(env: Env) -> None:
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    when = at(env, hours=2)
    v1, visit_id = visit_event(env, doctor_id=doctor_id, scheduled_at=when)
    await post_sync(env, token, [d_ev, v1])
    # Mismo hecho reenviado con otro event_id: idempotente por entidad.
    same, _ = visit_event(env, doctor_id=doctor_id, scheduled_at=when, visit_id=visit_id)
    assert (await post_sync(env, token, [same]))["results"][0]["status"] == "applied"
    assert await count(env, Visit) == 1
    # Mismo visit_id con otros datos: conflicto.
    diff, _ = visit_event(
        env, doctor_id=doctor_id, scheduled_at=at(env, hours=8), visit_id=visit_id
    )
    assert (await post_sync(env, token, [diff]))["results"][0]["reason"] == "visit_id_conflict"


async def test_doctor_created_rules(env: Env) -> None:
    token = await rep_token(env)
    inst = {"id": str(uuid7()), "name": "Hospital del Valle"}
    a, doctor_id = doctor_event(env, institution=inst)
    # Mismo médico reenviado con otro event_id → idempotente.
    b, _ = doctor_event(env, doctor_id=doctor_id, institution=inst)
    # Institución existente reutilizada por id y otro médico.
    c, _ = doctor_event(env, name="Dr. Pedro Ríos", institution=inst)
    # Institución ambigua.
    bad = doctor_event(env, name="Dr. Ambiguo")[0]
    bad["payload"]["institution_id"] = str(uuid7())
    # Línea inexistente.
    bad2 = doctor_event(env, name="Dra. Sin Línea")[0]
    bad2["payload"]["default_line_id"] = str(uuid7())
    out = await post_sync(env, token, [a, b, c, bad, bad2])
    assert [r["status"] for r in out["results"]] == [
        "applied",
        "applied",
        "applied",
        "rejected",
        "rejected",
    ]
    assert [r["reason"] for r in out["results"][3:]] == ["institution_ambiguous", "unknown_line"]
    state = await get_state(env, token)
    assert sorted(d["full_name"] for d in state["doctors"]) == [
        "Dr. Pedro Ríos",
        "Dra. Laura Méndez",
    ]
    assert [i["name"] for i in state["institutions"]] == ["Hospital del Valle"]


async def test_doctor_id_owned_by_another_rep_is_rejected(env: Env) -> None:
    ana = await rep_token(env, name="Ana")
    bob = await rep_token(env, phone=OTHER_PHONE, name="Bob")
    a, doctor_id = doctor_event(env)
    await post_sync(env, ana, [a])
    clash, _ = doctor_event(env, doctor_id=doctor_id)
    assert (await post_sync(env, bob, [clash]))["results"][0]["reason"] == "doctor_id_conflict"


async def test_batch_limit_and_clock_skew(env: Env) -> None:
    token = await rep_token(env)
    too_many = [ev("visit_not_done", {"reason": "other"}, visit_id=uuid7()) for _ in range(101)]
    await post_sync(env, token, too_many, expect=422)

    out = await post_sync(env, token, [], sent_at=clock.now() + timedelta(minutes=12))
    assert out["clock_skew_s"] == 12 * 60


async def test_sync_records_device(env: Env) -> None:
    from uno.modules.auth.models import Device

    token = await rep_token(env)
    device = uuid.uuid4()
    d_ev, _ = doctor_event(env)
    await post_sync(env, token, [d_ev], device_id=device)
    async with env.ctx.sessionmaker() as s:
        row = await s.get(Device, device)
    assert row is not None and row.outbox_pending == 1 and row.app_version == "test"


# ------------------------------------------------------------------ estado incremental


async def test_incremental_state_returns_only_changes(env: Env) -> None:
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    v1, vid1 = visit_event(env, doctor_id=doctor_id, scheduled_at=at(env, hours=2))
    await post_sync(env, token, [d_ev, v1])
    first = await get_state(env, token)
    cursor = first["cursor"]
    assert cursor > 0

    quiet = await get_state(env, token, cursor)
    assert quiet["full"] is False
    assert quiet["visits"] == [] and quiet["doctors"] == [] and quiet["institutions"] == []
    assert quiet["cursor"] == cursor

    v2, vid2 = visit_event(env, doctor_id=doctor_id, scheduled_at=at(env, hours=4))
    resched = ev("visit_rescheduled", {"scheduled_at": at(env, hours=6).isoformat()}, visit_id=vid1)
    await post_sync(env, token, [v2, resched])
    delta = await get_state(env, token, cursor)
    assert sorted(v["id"] for v in delta["visits"]) == sorted([str(vid1), str(vid2)])
    assert delta["doctors"] == []
    assert delta["cursor"] > cursor


async def test_state_with_cursor_ahead_of_server_is_full(env: Env) -> None:
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    v1, _ = visit_event(env, doctor_id=doctor_id, scheduled_at=at(env, hours=2))
    await post_sync(env, token, [d_ev, v1])
    state = await get_state(env, token, cursor=10_000)
    assert state["full"] is True and len(state["visits"]) == 1


async def test_full_state_only_covers_the_window(env: Env) -> None:
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    events = [d_ev]
    ids = {}
    for label, delta in {
        "old": timedelta(days=-9),
        "past_ok": timedelta(days=-3),
        "future_ok": timedelta(days=10),
        "far": timedelta(days=20),
    }.items():
        e, vid = visit_event(env, doctor_id=doctor_id, scheduled_at=clock.now() + delta)
        events.append(e)
        ids[label] = str(vid)
    await post_sync(env, token, events)
    state = await get_state(env, token)
    got = {v["id"] for v in state["visits"]}
    assert got == {ids["past_ok"], ids["future_ok"]}
    # Lo que quedó fuera de la ventana sí llega por cambios incrementales.
    later = await get_state(env, token, cursor=1)
    assert ids["old"] in {v["id"] for v in later["visits"]}


async def test_change_seq_is_strictly_increasing(env: Env) -> None:
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    seqs = []
    await post_sync(env, token, [d_ev])
    seqs.append((await get_state(env, token))["cursor"])
    for i in range(3):
        v, _ = visit_event(env, doctor_id=doctor_id, scheduled_at=at(env, hours=i + 1))
        await post_sync(env, token, [v])
        seqs.append((await get_state(env, token))["cursor"])
    assert seqs == sorted(set(seqs))


# ------------------------------------------------------------------ bitácora de dominio


async def test_domain_events_are_emitted_without_personal_data(env: Env) -> None:
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env, name="Dra. Laura Méndez")
    v_ev, visit_id = visit_event(env, doctor_id=doctor_id, scheduled_at=at(env, hours=2))
    resched = ev(
        "visit_rescheduled", {"scheduled_at": at(env, hours=3).isoformat()}, visit_id=visit_id
    )
    await post_sync(env, token, [d_ev, v_ev, resched])
    async with env.ctx.sessionmaker() as s:
        rows = (
            (await s.execute(select(DomainEvent).order_by(DomainEvent.recorded_at))).scalars().all()
        )
    assert sorted(r.event_type for r in rows) == [
        "doctor_created",
        "visit_rescheduled",
        "visit_scheduled",
    ]
    sched = next(r for r in rows if r.event_type == "visit_scheduled")
    assert sched.entities["visit_id"] == str(visit_id)
    assert sched.entities["doctor_id"] == str(doctor_id)
    assert sched.entities["product_line_ids"] == [str(env.lines["GASTRU"])]
    assert sched.correlation_id == visit_id
    assert sched.occurred_at.isoformat() == v_ev["device_ts"]  # hora del hecho (teléfono)
    assert sched.recorded_at == clock.now()  # hora en que lo supo el servidor
    blob = " ".join(str(r.payload) + str(r.entities) for r in rows)
    assert "Méndez" not in blob and "Clínica" not in blob


# ------------------------------------------------------------------ robustez


async def test_crash_while_applying_is_retried_on_resend(env: Env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """El servidor cae a mitad de camino: el evento queda `received` y se aplica al reintentar."""
    from uno.modules.sync.registry import _REGISTRY, Registration

    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    real = _REGISTRY["doctor_created"]
    calls = {"n": 0}

    async def flaky(ctx, payload):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("caída simulada")
        await real.fn(ctx, payload)

    monkeypatch.setitem(
        _REGISTRY, "doctor_created", Registration("doctor_created", real.payload_model, flaky)
    )
    import pytest

    with pytest.raises(RuntimeError):
        await env.client.post(
            "/v1/sync",
            headers=bearer(token),
            json={
                "device_id": str(uuid.uuid4()),
                "sent_at": clock.now().isoformat(),
                "events": [d_ev],
            },
        )
    async with env.ctx.sessionmaker() as s:
        stored = await s.get(SyncEvent, uuid.UUID(d_ev["event_id"]))
    assert stored is not None and stored.status == "received"

    out = await post_sync(env, token, [d_ev])
    assert out["results"][0]["status"] == "applied"
    assert (await get_state(env, token))["doctors"][0]["id"] == str(doctor_id)


async def test_concurrent_identical_batches_apply_once(env: Env) -> None:
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    v_ev, _ = visit_event(env, doctor_id=doctor_id, scheduled_at=at(env, hours=2))
    await post_sync(env, token, [d_ev])
    results = await asyncio.gather(*[post_sync(env, token, [v_ev]) for _ in range(5)])
    statuses = [r["results"][0]["status"] for r in results]
    assert set(statuses) <= {"applied", "duplicate"}
    assert "applied" in statuses
    assert await count(env, Visit) == 1
    assert await count(env, SyncEvent) == 2


async def _scenario(env: Env, order_seed: int | None) -> dict:  # type: ignore[type-arg]
    """Un conjunto fijo de eventos, en orden natural o barajado y con duplicados."""
    token = await rep_token(env)
    base = clock.now()
    rnd = random.Random(order_seed)
    ids = [uuid.UUID(int=1000 + i) for i in range(4)]
    events: list[dict] = []  # type: ignore[type-arg]
    d_ev, doctor_id = doctor_event(
        env,
        doctor_id=uuid.UUID(int=999),
        ts=base,
        institution={"id": str(uuid.UUID(int=998)), "name": "Clínica Norte"},
        event_id=uuid.UUID(int=5000),
    )
    events.append(d_ev)
    for i, vid in enumerate(ids):
        v, _ = visit_event(
            env,
            doctor_id=doctor_id,
            scheduled_at=base + timedelta(hours=i + 2),
            visit_id=vid,
            ts=base + timedelta(seconds=10 + i),
            event_id=uuid.UUID(int=6000 + i),
        )
        events.append(v)
    events.append(
        ev(
            "visit_rescheduled",
            {"scheduled_at": (base + timedelta(hours=9)).isoformat()},
            visit_id=ids[0],
            ts=base + timedelta(seconds=30),
            event_id=uuid.UUID(int=7000),
        )
    )
    events.append(
        ev(
            "visit_not_done",
            {"reason": "other"},
            visit_id=ids[1],
            ts=base + timedelta(seconds=31),
            event_id=uuid.UUID(int=7001),
        )
    )
    batch = list(events)
    if order_seed is not None:
        batch = batch + rnd.sample(events, 4)  # duplicados
        rnd.shuffle(batch)
    # Dentro de un lote el orden no importa (se aplica por device_ts). Entre lotes el teléfono
    # envía en orden, con un candado que impide dos envíos simultáneos.
    await post_sync(env, token, batch)
    state = await get_state(env, token)
    return {
        "visits": [
            {k: v[k] for k in ("id", "status", "scheduled_at", "not_done_reason")}
            for v in state["visits"]
        ],
        "doctors": [d["full_name"] for d in state["doctors"]],
    }


async def test_final_state_is_the_same_for_any_order_and_duplicates(make_env) -> None:  # type: ignore[no-untyped-def]
    """T1.4 CA4 (versión de propiedades): permutar y duplicar eventos no cambia el estado final."""
    async with make_env() as base_env:
        expected = await _scenario(base_env, None)
    assert len(expected["visits"]) == 4
    for seed in range(6):
        async with make_env() as e:
            got = await _scenario(e, seed)
        assert got == expected, f"semilla {seed}"


class _AnyPayload(BaseModel):
    model_config = ConfigDict(extra="allow")


class _FakeRegistration:
    """Un manejador que choca con un intento concurrente del mismo evento."""

    payload_model = _AnyPayload

    def __init__(self, winner_marks_applied: bool) -> None:
        self.winner_marks_applied = winner_marks_applied

    async def fn(self, ctx: Any, payload: Any) -> None:
        from sqlalchemy import update
        from sqlalchemy.exc import IntegrityError

        if self.winner_marks_applied:  # el otro intento terminó y confirmó justo ahora
            async with ctx.session.bind.connect() as conn:  # type: ignore[union-attr]
                await conn.execute(
                    update(SyncEvent)
                    .where(SyncEvent.event_id == ctx.event_id)
                    .values(status="applied")
                )
                await conn.commit()
        raise IntegrityError("INSERT INTO visit", {}, Exception("UNIQUE constraint failed: visit.id"))


async def test_a_lost_race_against_the_same_event_is_a_duplicate_not_a_500(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = await rep_token(env)
    d_ev, _ = doctor_event(env)
    monkeypatch.setattr(sync_service, "get_handler", lambda _t: _FakeRegistration(True))
    body = await post_sync(env, token, [d_ev])
    assert body["results"][0]["status"] == "duplicate"


async def test_a_real_integrity_error_is_not_swallowed(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    token = await rep_token(env)
    d_ev, _ = doctor_event(env)
    monkeypatch.setattr(sync_service, "get_handler", lambda _t: _FakeRegistration(False))
    with pytest.raises(Exception):  # noqa: B017, PT011 - sube como error del servidor, no como "duplicado"
        await post_sync(env, token, [d_ev], expect=200)
