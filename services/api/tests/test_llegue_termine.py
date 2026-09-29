"""«Llegué» / «Terminé» + ubicación (módulo E4): eventos, geocerca y bajada de estado."""

from __future__ import annotations

import asyncio
import itertools
import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from uno import clock
from uno.events import DomainEvent
from uno.ids import uuid7
from uno.modules.agenda.models import Visit
from uno.modules.catalog.models import Institution

from .conftest import OTHER_PHONE, Env, rep_token
from .helpers import (
    arrived_event,
    doctor_event,
    ev,
    finished_event,
    get_state,
    location,
    post_sync,
    retry_event,
    set_institution_reference,
    visit_event,
)

# Referencia de la institución de prueba (la misma de la tabla compartida de geocerca).
REF_LAT, REF_LNG = 4.6765, -74.0481

# Lecturas de la tabla compartida (`docs/contratos/geocerca-casos.json`), con radio 300 m.
AT_100M = (4.675601, REF_LNG)  # a 100 m
AT_850M = (4.684144, REF_LNG)  # a 850 m


def at(**delta: float) -> datetime:
    return clock.now() + timedelta(**delta)


async def get_visit(env: Env, visit_id: uuid.UUID) -> Visit:
    async with env.ctx.sessionmaker() as s:
        visit = await s.get(Visit, visit_id)
    assert visit is not None
    return visit


async def domain_events(env: Env, event_type: str) -> list[DomainEvent]:
    async with env.ctx.sessionmaker() as s:
        rows = await s.execute(
            select(DomainEvent)
            .where(DomainEvent.event_type == event_type)
            .order_by(DomainEvent.recorded_at)
        )
        return list(rows.scalars())


async def only_visit_state(env: Env, token: str, visit_id: uuid.UUID) -> dict[str, Any]:
    state = await get_state(env, token)
    (visit,) = [v for v in state["visits"] if v["id"] == str(visit_id)]
    return visit


def assert_no_coordinates(data: dict[str, Any], loc: dict[str, Any] | None = None) -> None:
    """La bitácora y la bajada de estado no llevan coordenadas (política de events.py)."""
    assert not {"lat", "lng", "latitude", "longitude"} & set(data), data
    if loc is not None:
        assert str(loc["lat"]) not in str(data) and str(loc["lng"]) not in str(data), data


async def setup_visit(
    env: Env, token: str, *, reference: bool = True
) -> tuple[uuid.UUID, uuid.UUID]:
    """Médico + institución + visita agendada. Devuelve (visit_id, institution_id)."""
    inst_id = uuid7()
    inst = {"id": str(inst_id), "name": "Hospital San Rafael", "city": "Bogotá"}
    d_ev, doctor_id = doctor_event(env, institution=inst)
    v_ev, visit_id = visit_event(env, doctor_id=doctor_id, scheduled_at=at(hours=1))
    out = await post_sync(env, token, [d_ev, v_ev])
    assert [r["status"] for r in out["results"]] == ["applied", "applied"]
    if reference:
        await set_institution_reference(env, inst_id, REF_LAT, REF_LNG)
    return visit_id, inst_id


async def send(env: Env, token: str, event: dict[str, Any]) -> dict[str, Any]:
    (result,) = (await post_sync(env, token, [event]))["results"]
    return result


# ------------------------------------------------------------------ Llegué + geocerca


@pytest.mark.parametrize(
    ("has_reference", "reading", "state", "distance_m", "precision_m"),
    [
        pytest.param(True, (*AT_100M, 10), "verificada", 100, 10, id="verificada"),
        pytest.param(True, (*AT_850M, 15), "lejos", 850, 15, id="lejos"),
        pytest.param(True, (REF_LAT, REF_LNG, 150), "imprecisa", 0, 150, id="imprecisa"),
        pytest.param(False, (*AT_100M, 10), "sin_referencia", None, 10, id="sin_referencia"),
        pytest.param(True, None, "sin_gps", None, None, id="sin_gps"),
    ],
)
async def test_arrival_geofence_states(
    env: Env,
    has_reference: bool,
    reading: tuple[float, float, float] | None,
    state: str,
    distance_m: int | None,
    precision_m: float | None,
) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token, reference=has_reference)
    loc = location(*reading) if reading is not None else None
    touch = at(minutes=10)
    arrived = arrived_event(visit_id, loc, ts=touch)
    assert (await send(env, token, arrived))["status"] == "applied"

    row = await get_visit(env, visit_id)
    assert row.status == "in_progress"
    assert row.arrived_at == touch  # hora del toque en el teléfono
    assert row.arrival_geo_state == state
    assert row.arrival_distance_m == distance_m
    assert row.arrival_precision_m == precision_m
    if loc is None:
        assert (row.arrival_lat, row.arrival_lng, row.arrival_source, row.arrival_fix_ts) == (
            None,
            None,
            None,
            None,
        )
    else:
        assert (row.arrival_lat, row.arrival_lng) == (loc["lat"], loc["lng"])
        assert row.arrival_source == "gps"
        assert row.arrival_fix_ts == clock.now()
    # «Terminé» aún no existe.
    assert row.finished_at is None and row.finish_geo_state is None

    # Bajada de estado: estado, distancia y precisión; nunca lat/lng.
    visit = await only_visit_state(env, token, visit_id)
    assert visit["status"] == "in_progress"
    assert visit["arrival_geo"] == {
        "state": state,
        "distance_m": distance_m,
        "precision_m": precision_m,
    }
    assert visit["arrived_at"].startswith(touch.strftime("%Y-%m-%dT%H:%M"))
    assert visit["finish_geo"] is None and visit["finished_at"] is None
    assert set(visit["arrival_geo"]) == {"state", "distance_m", "precision_m"}  # sin lat/lng
    assert_no_coordinates(visit, loc)


async def test_visit_without_institution_is_sin_referencia(env: Env) -> None:
    token = await rep_token(env)
    d_ev, doctor_id = doctor_event(env)
    del d_ev["payload"]["institution"]  # médico sin institución
    v_ev, visit_id = visit_event(env, doctor_id=doctor_id, scheduled_at=at(hours=1))
    await post_sync(env, token, [d_ev, v_ev])
    arrived = arrived_event(visit_id, location(*AT_100M, 10))
    assert (await send(env, token, arrived))["status"] == "applied"
    assert (await get_visit(env, visit_id)).arrival_geo_state == "sin_referencia"


async def test_institution_with_only_one_coordinate_is_sin_referencia(env: Env) -> None:
    token = await rep_token(env)
    visit_id, inst_id = await setup_visit(env, token, reference=False)
    await set_institution_reference(env, inst_id, REF_LAT, None)
    await send(env, token, arrived_event(visit_id, location(*AT_100M, 10)))
    assert (await get_visit(env, visit_id)).arrival_geo_state == "sin_referencia"


async def test_reused_location_source_is_stored(env: Env) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    loc = location(*AT_100M, 10, source="reused")
    assert (await send(env, token, arrived_event(visit_id, loc)))["status"] == "applied"
    row = await get_visit(env, visit_id)
    assert row.arrival_source == "reused" and row.arrival_geo_state == "verificada"


async def test_arrival_missing_location_key_is_sin_gps(env: Env) -> None:
    """Nunca se pierde una visita por falta de GPS: sin `location` en el payload, `sin_gps`."""
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    bare = ev("visit_arrived", {}, visit_id=visit_id)
    assert (await send(env, token, bare))["status"] == "applied"
    assert (await get_visit(env, visit_id)).arrival_geo_state == "sin_gps"


async def test_arrival_domain_event_has_diagnostics_but_no_coordinates(env: Env) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    loc = location(*AT_100M, 10)
    arrived = arrived_event(
        visit_id, loc, ts=at(minutes=5), permission="granted", duration_ms=1840, error=None
    )
    await send(env, token, arrived)
    (event,) = await domain_events(env, "visit_arrived")
    assert event.payload == {
        "geo_state": "verificada",
        "distance_m": 100,
        "precision_m": 10,
        "location_source": "gps",
        "fix_ts": clock.now().isoformat(),
        "permission": "granted",
        "duration_ms": 1840,
        "error": None,
    }
    assert event.entities["visit_id"] == str(visit_id)
    assert event.correlation_id == visit_id
    assert event.causation_id == uuid.UUID(arrived["event_id"])
    assert event.occurred_at == at(minutes=5)  # hora del toque
    # La política de la bitácora prohíbe coordenadas: viven solo en la tabla `visit`.
    assert_no_coordinates(event.payload, loc)
    assert_no_coordinates(event.entities, loc)


async def test_arrival_without_gps_records_the_error_in_the_event(env: Env) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    long_error = "x" * 500  # un diagnóstico largo se recorta, no cuesta la visita
    arrived = arrived_event(visit_id, None, permission="denied", duration_ms=0, error=long_error)
    assert (await send(env, token, arrived))["status"] == "applied"
    (event,) = await domain_events(env, "visit_arrived")
    assert event.payload["geo_state"] == "sin_gps"
    assert event.payload["permission"] == "denied" and event.payload["duration_ms"] == 0
    assert event.payload["error"] == "x" * 120
    assert event.payload["precision_m"] is None and event.payload["distance_m"] is None


@pytest.mark.parametrize("prior", ["not_done", "in_progress", "finished"])
async def test_arrival_on_a_visit_that_is_not_scheduled_is_rejected(env: Env, prior: str) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    setup: dict[str, dict[str, Any]] = {
        "not_done": ev("visit_not_done", {"reason": "other"}, visit_id=visit_id),
        "in_progress": arrived_event(visit_id, None),
        "finished": finished_event(visit_id, None),
    }
    assert (await send(env, token, setup[prior]))["status"] == "applied"
    result = await send(env, token, arrived_event(visit_id, location(*AT_100M, 10)))
    assert (result["status"], result["reason"]) == ("rejected", "visit_not_editable")
    # Ninguna llegada nueva quedó en la bitácora (la de `in_progress` es la del arreglo previo).
    assert len(await domain_events(env, "visit_arrived")) == (1 if prior == "in_progress" else 0)
    if prior != "in_progress":
        assert (await get_visit(env, visit_id)).arrived_at is None


async def test_visit_in_progress_cannot_be_rescheduled_or_dropped(env: Env) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    await send(env, token, arrived_event(visit_id, None))
    resched = ev("visit_rescheduled", {"scheduled_at": at(hours=5).isoformat()}, visit_id=visit_id)
    not_done = ev("visit_not_done", {"reason": "other"}, visit_id=visit_id)
    out = await post_sync(env, token, [resched, not_done])
    assert [r["reason"] for r in out["results"]] == ["visit_not_editable"] * 2


# ------------------------------------------------------------------ Terminé


async def test_finish_after_arrival(env: Env) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    t_arrive, t_finish = at(minutes=10), at(minutes=40)
    await send(env, token, arrived_event(visit_id, location(*AT_100M, 10), ts=t_arrive))
    finished = finished_event(
        visit_id, location(*AT_850M, 20), ts=t_finish, permission="granted", duration_ms=900
    )
    assert (await send(env, token, finished))["status"] == "applied"

    row = await get_visit(env, visit_id)
    assert row.status == "finished"
    assert row.arrived_at == t_arrive and row.finished_at == t_finish
    assert (row.arrival_geo_state, row.finish_geo_state) == ("verificada", "lejos")
    assert (row.finish_lat, row.finish_lng, row.finish_precision_m) == (*AT_850M, 20)
    assert row.finish_distance_m == 850 and row.finish_source == "gps"
    # La llegada no se toca al terminar.
    assert (row.arrival_lat, row.arrival_distance_m) == (AT_100M[0], 100)

    visit = await only_visit_state(env, token, visit_id)
    assert visit["status"] == "finished"
    assert visit["arrival_geo"]["state"] == "verificada"
    assert visit["finish_geo"] == {"state": "lejos", "distance_m": 850, "precision_m": 20}

    (event,) = await domain_events(env, "visit_finished")
    assert event.payload["geo_state"] == "lejos" and event.payload["without_arrival"] is False
    assert event.payload["permission"] == "granted" and event.payload["duration_ms"] == 900
    assert_no_coordinates(event.payload, location(*AT_850M, 20))


async def test_finish_from_scheduled_leaves_arrived_at_empty(env: Env) -> None:
    """«Terminé» sin «Llegué»: la visita queda finished y `arrived_at` nulo (señal «sin llegada»)."""
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    t_finish = at(minutes=30)
    finished = finished_event(visit_id, location(*AT_100M, 10), ts=t_finish)
    assert (await send(env, token, finished))["status"] == "applied"

    row = await get_visit(env, visit_id)
    assert row.status == "finished" and row.finished_at == t_finish
    assert row.arrived_at is None and row.arrival_geo_state is None
    assert row.finish_geo_state == "verificada"

    visit = await only_visit_state(env, token, visit_id)
    assert visit["arrived_at"] is None and visit["arrival_geo"] is None
    assert visit["finish_geo"]["state"] == "verificada"
    (event,) = await domain_events(env, "visit_finished")
    assert event.payload["without_arrival"] is True


async def test_finish_without_gps(env: Env) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    await send(env, token, arrived_event(visit_id, location(*AT_100M, 10)))
    assert (await send(env, token, finished_event(visit_id, None)))["status"] == "applied"
    visit = await only_visit_state(env, token, visit_id)
    assert visit["finish_geo"] == {"state": "sin_gps", "distance_m": None, "precision_m": None}


async def test_finish_on_not_done_or_finished_is_rejected(env: Env) -> None:
    token = await rep_token(env)
    dropped, _ = await setup_visit(env, token)
    await send(env, token, ev("visit_not_done", {"reason": "other"}, visit_id=dropped))
    result = await send(env, token, finished_event(dropped, None))
    assert (result["status"], result["reason"]) == ("rejected", "visit_not_editable")
    assert (await get_visit(env, dropped)).finished_at is None

    done, _ = await setup_visit(env, token)
    await send(env, token, finished_event(done, None, ts=at(minutes=1)))
    again = await send(env, token, finished_event(done, location(*AT_100M, 10), ts=at(minutes=2)))
    assert (again["status"], again["reason"]) == ("rejected", "visit_not_editable")
    # La evidencia no cambia con el segundo intento.
    row = await get_visit(env, done)
    assert row.finished_at == at(minutes=1) and row.finish_geo_state == "sin_gps"


# ------------------------------------------------------------------ Reintentar ubicación


async def test_retry_replaces_the_arrival_location_and_recomputes(env: Env) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    t_arrive = at(minutes=10)
    await send(env, token, arrived_event(visit_id, None, ts=t_arrive, permission="prompt"))
    assert (await get_visit(env, visit_id)).arrival_geo_state == "sin_gps"
    cursor = (await get_state(env, token))["cursor"]

    good = location(*AT_100M, 12, fix_ts=t_arrive + timedelta(seconds=40))
    retry = retry_event(
        visit_id, "arrival", good, ts=t_arrive + timedelta(seconds=45), duration_ms=2200
    )
    assert (await send(env, token, retry))["status"] == "applied"

    row = await get_visit(env, visit_id)
    assert row.status == "in_progress"
    assert row.arrived_at == t_arrive  # el toque no se mueve
    assert row.arrival_geo_state == "verificada" and row.arrival_distance_m == 100
    assert (row.arrival_lat, row.arrival_lng, row.arrival_precision_m) == (*AT_100M, 12)
    assert row.arrival_fix_ts == t_arrive + timedelta(seconds=40)

    # El teléfono la recibe en la bajada incremental.
    delta = await get_state(env, token, cursor)
    (visit,) = delta["visits"]
    assert visit["arrival_geo"] == {"state": "verificada", "distance_m": 100, "precision_m": 12}

    (event,) = await domain_events(env, "visit_location_retried")
    assert event.payload["moment"] == "arrival"
    assert event.payload["previous_geo_state"] == "sin_gps"
    assert event.payload["geo_state"] == "verificada" and event.payload["duration_ms"] == 2200
    assert_no_coordinates(event.payload, good)


async def test_retry_of_an_imprecise_finish_reading(env: Env) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    t_arrive, t_finish = at(minutes=10), at(minutes=30)
    await send(env, token, arrived_event(visit_id, location(*AT_100M, 10), ts=t_arrive))
    await send(env, token, finished_event(visit_id, location(*AT_100M, 180), ts=t_finish))
    assert (await get_visit(env, visit_id)).finish_geo_state == "imprecisa"

    retry = retry_event(
        visit_id, "finish", location(*AT_100M, 15), ts=t_finish + timedelta(seconds=90)
    )
    assert (await send(env, token, retry))["status"] == "applied"
    row = await get_visit(env, visit_id)
    assert (row.finish_geo_state, row.finish_distance_m) == ("verificada", 100)
    assert row.finished_at == t_finish and row.arrival_geo_state == "verificada"


async def test_retry_window_is_two_minutes_inclusive(env: Env) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    t_arrive = at(minutes=10)
    await send(env, token, arrived_event(visit_id, None, ts=t_arrive))
    good = location(*AT_100M, 10)

    late = retry_event(visit_id, "arrival", good, ts=t_arrive + timedelta(minutes=2, seconds=1))
    result = await send(env, token, late)
    assert (result["status"], result["reason"]) == ("rejected", "retry_window_expired")
    assert (await get_visit(env, visit_id)).arrival_geo_state == "sin_gps"

    on_time = retry_event(visit_id, "arrival", good, ts=t_arrive + timedelta(minutes=2))
    assert (await send(env, token, on_time))["status"] == "applied"
    assert (await get_visit(env, visit_id)).arrival_geo_state == "verificada"


@pytest.mark.parametrize(
    "reading",
    [(*AT_100M, 10), (*AT_850M, 15)],
    ids=["verificada", "lejos"],
)
async def test_retry_is_rejected_when_the_state_is_not_sin_gps_or_imprecisa(
    env: Env, reading: tuple[float, float, float]
) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    t_arrive = at(minutes=10)
    await send(env, token, arrived_event(visit_id, location(*reading), ts=t_arrive))
    before = await get_visit(env, visit_id)
    retry = retry_event(
        visit_id, "arrival", location(*AT_850M, 10), ts=t_arrive + timedelta(seconds=30)
    )
    result = await send(env, token, retry)
    assert (result["status"], result["reason"]) == ("rejected", "location_not_retryable")
    after = await get_visit(env, visit_id)
    assert (after.arrival_lat, after.arrival_geo_state) == (
        before.arrival_lat,
        before.arrival_geo_state,
    )
    assert await domain_events(env, "visit_location_retried") == []


async def test_retry_checks_retryable_state_before_the_window(env: Env) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    t_arrive = at(minutes=10)
    await send(env, token, arrived_event(visit_id, location(*AT_100M, 10), ts=t_arrive))
    late = retry_event(
        visit_id, "arrival", location(*AT_100M, 10), ts=t_arrive + timedelta(hours=1)
    )
    assert (await send(env, token, late))["reason"] == "location_not_retryable"


async def test_retry_of_a_touch_that_does_not_exist_is_rejected(env: Env) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    good = location(*AT_100M, 10)

    # Visita agendada: no hay ni llegada ni cierre.
    out = await post_sync(
        env,
        token,
        [
            retry_event(visit_id, "arrival", good, ts=at(minutes=1)),
            retry_event(visit_id, "finish", good, ts=at(minutes=1)),
        ],
    )
    assert [r["reason"] for r in out["results"]] == ["visit_not_editable"] * 2

    # En curso: hay llegada pero no cierre.
    await send(env, token, arrived_event(visit_id, None, ts=at(minutes=2)))
    result = await send(
        env, token, retry_event(visit_id, "finish", good, ts=at(minutes=2, seconds=5))
    )
    assert result["reason"] == "visit_not_editable"

    # «Terminé sin Llegué»: hay cierre pero no llegada.
    other, _ = await setup_visit(env, token)
    await send(env, token, finished_event(other, None, ts=at(minutes=3)))
    result = await send(
        env, token, retry_event(other, "arrival", good, ts=at(minutes=3, seconds=5))
    )
    assert result["reason"] == "visit_not_editable"
    assert (await get_visit(env, other)).arrived_at is None


async def test_retry_requires_a_location(env: Env) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    await send(env, token, arrived_event(visit_id, None, ts=at(minutes=1)))
    for bad in (None, "no-es-un-objeto"):
        result = await send(env, token, retry_event(visit_id, "arrival", bad, ts=at(minutes=1)))  # type: ignore[arg-type]
        assert result["reason"] == "invalid_payload"
    bad_moment = retry_event(visit_id, "midday", location(*AT_100M, 10), ts=at(minutes=1))
    assert (await send(env, token, bad_moment))["reason"] == "invalid_payload"


# ------------------------------------------------------------------ idempotencia y orden


async def test_same_event_twice_is_a_duplicate_and_changes_once(env: Env) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    arrived = arrived_event(visit_id, location(*AT_100M, 10), ts=at(minutes=1))
    retry_target, _ = await setup_visit(env, token)
    await send(env, token, arrived_event(retry_target, None, ts=at(minutes=1)))
    retry = retry_event(
        retry_target, "arrival", location(*AT_100M, 10), ts=at(minutes=1, seconds=20)
    )

    first = await post_sync(env, token, [arrived, retry])
    cursor = (await get_state(env, token))["cursor"]
    second = await post_sync(env, token, [arrived, retry])
    assert [r["status"] for r in first["results"]] == ["applied", "applied"]
    assert [r["status"] for r in second["results"]] == ["duplicate", "duplicate"]
    assert (await get_state(env, token))["cursor"] == cursor  # el reenvío no cambió nada
    assert len(await domain_events(env, "visit_arrived")) == 2  # las dos llegadas (una por visita)
    assert len(await domain_events(env, "visit_location_retried")) == 1


async def test_unordered_batch_gives_the_same_final_state_in_any_permutation(env: Env) -> None:
    """scheduled + arrived + finished (con el médico) por `device_ts`: toda permutación coincide."""
    token = await rep_token(env)
    _, inst_id = await setup_visit(env, token)  # crea la institución con su referencia
    inst = {"id": str(inst_id), "name": "Hospital San Rafael"}
    t0 = clock.now()

    def scenario() -> tuple[list[dict[str, Any]], uuid.UUID]:
        d_ev, doctor_id = doctor_event(env, institution=inst, ts=t0)
        v_ev, visit_id = visit_event(
            env, doctor_id=doctor_id, scheduled_at=at(hours=2), ts=t0 + timedelta(seconds=1)
        )
        a_ev = arrived_event(visit_id, location(*AT_100M, 10), ts=t0 + timedelta(seconds=60))
        f_ev = finished_event(visit_id, location(*AT_850M, 20), ts=t0 + timedelta(seconds=600))
        return [d_ev, v_ev, a_ev, f_ev], visit_id

    def final(visit: dict[str, Any]) -> dict[str, Any]:
        keep = ("status", "arrived_at", "finished_at", "arrival_geo", "finish_geo")
        return {k: visit[k] for k in keep}

    events, visit_id = scenario()
    out = await post_sync(env, token, events)
    assert [r["status"] for r in out["results"]] == ["applied"] * 4
    expected = final(await only_visit_state(env, token, visit_id))
    assert expected["status"] == "finished"
    assert expected["arrival_geo"]["state"] == "verificada"
    assert expected["finish_geo"]["state"] == "lejos"

    for order in itertools.permutations(range(4)):
        events, visit_id = scenario()
        out = await post_sync(env, token, [events[i] for i in order])
        assert [r["status"] for r in out["results"]] == ["applied"] * 4, order
        assert final(await only_visit_state(env, token, visit_id)) == expected, order


# ------------------------------------------------------------------ seguridad y validación


async def test_someone_elses_visit_is_unknown(env: Env) -> None:
    ana = await rep_token(env, name="Ana")
    bob = await rep_token(env, phone=OTHER_PHONE, name="Bob")
    visit_id, _ = await setup_visit(env, ana)
    await send(env, ana, arrived_event(visit_id, None, ts=at(minutes=1)))
    good = location(*AT_100M, 10)
    out = await post_sync(
        env,
        bob,
        [
            arrived_event(visit_id, good),
            finished_event(visit_id, good),
            retry_event(visit_id, "arrival", good, ts=at(minutes=1, seconds=10)),
        ],
    )
    assert [(r["status"], r["reason"]) for r in out["results"]] == [
        ("rejected", "unknown_visit")
    ] * 3
    # Y no tocaron nada de Ana.
    row = await get_visit(env, visit_id)
    assert row.status == "in_progress" and row.arrival_geo_state == "sin_gps"


async def test_unknown_visit_and_missing_visit_id(env: Env) -> None:
    token = await rep_token(env)
    ghost = uuid7()
    no_id = [
        ev("visit_arrived", {"location": None}),
        ev("visit_finished", {"location": None}),
        ev(
            "visit_location_retried",
            {"moment": "arrival", "location": location(*AT_100M, 10)},
        ),
    ]
    with_ghost = [
        arrived_event(ghost, None),
        finished_event(ghost, None),
        retry_event(ghost, "arrival", location(*AT_100M, 10)),
    ]
    out = await post_sync(env, token, no_id + with_ghost)
    assert [r["reason"] for r in out["results"]] == ["visit_id_required"] * 3 + [
        "unknown_visit"
    ] * 3


@pytest.mark.parametrize(
    "bad",
    [
        {**location(*AT_100M, 10), "lat": 91},
        {**location(*AT_100M, 10), "lat": -90.5},
        {**location(*AT_100M, 10), "lng": 180.1},
        {**location(*AT_100M, 10), "lng": -181},
        {**location(*AT_100M, 10), "precision_m": -1},
        {**location(*AT_100M, 10), "fix_ts": "2026-09-29T12:00:00"},  # sin zona horaria
        {**location(*AT_100M, 10), "source": "wifi"},
        {k: v for k, v in location(*AT_100M, 10).items() if k != "fix_ts"},
    ],
    ids=[
        "lat>90",
        "lat<-90",
        "lng>180",
        "lng<-180",
        "precision<0",
        "fix_ts_naive",
        "source",
        "sin_fix_ts",
    ],
)
async def test_invalid_location_payloads_are_rejected(env: Env, bad: dict[str, Any]) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    result = await send(env, token, arrived_event(visit_id, bad))
    assert (result["status"], result["reason"]) == ("rejected", "invalid_payload")
    assert (await get_visit(env, visit_id)).status == "scheduled"


@pytest.mark.parametrize(
    "diagnostics",
    [{"permission": "maybe"}, {"duration_ms": -1}],
    ids=["permission", "duration_ms"],
)
async def test_invalid_diagnostics_are_rejected(env: Env, diagnostics: dict[str, Any]) -> None:
    token = await rep_token(env)
    visit_id, _ = await setup_visit(env, token)
    result = await send(env, token, arrived_event(visit_id, None, **diagnostics))
    assert result["reason"] == "invalid_payload"


# ------------------------------------------------------------------ institución y semilla


async def test_default_institution_radius_is_300(env: Env) -> None:
    token = await rep_token(env)
    inst_id = uuid7()
    d_ev, _ = doctor_event(env, institution={"id": str(inst_id), "name": "Clínica del Norte"})
    await post_sync(env, token, [d_ev])
    async with env.ctx.sessionmaker() as s:
        inst = await s.get(Institution, inst_id)
    assert inst is not None and inst.radius_m == 300
    assert inst.lat is None and inst.lng is None  # sin referencia hasta que alguien la fije
    (out,) = (await get_state(env, token))["institutions"]
    assert out["radius_m"] == 300 and out["lat"] is None


async def test_geofence_uses_the_institution_radius(env: Env) -> None:
    """A 190 m con precisión 40: verificada (radio 300), pero lejos con un radio de 100 m."""
    token = await rep_token(env)
    near_190 = location(4.678209, REF_LNG, 40)
    a, _ = await setup_visit(env, token)
    b, inst_b = await setup_visit(env, token)
    await set_institution_reference(env, inst_b, REF_LAT, REF_LNG, radius_m=100)
    await send(env, token, arrived_event(a, near_190, ts=at(minutes=1)))
    await send(env, token, arrived_event(b, near_190, ts=at(minutes=1)))
    assert (await get_visit(env, a)).arrival_geo_state == "verificada"
    assert (await get_visit(env, b)).arrival_geo_state == "lejos"
    assert (await get_visit(env, a)).arrival_distance_m == 190


async def test_demo_seed_sets_reference_on_two_institutions(env: Env) -> None:
    from uno.seed import seed_demo

    await seed_demo(env.ctx)
    async with env.ctx.sessionmaker() as s:
        rows = {i.name: i for i in (await s.execute(select(Institution))).scalars()}
    for name in ("Hospital San Rafael", "Hospital del Valle"):
        inst = rows[name]
        assert inst.lat is not None and inst.lng is not None
        assert 4.4 < inst.lat < 4.9 and -74.3 < inst.lng < -73.9  # Bogotá
        assert inst.ref_source == "manual" and inst.radius_m == 300
    assert rows["Clínica Central"].lat is None and rows["Clínica Moderna"].lat is None

    # Repetir la semilla no vuelve a tocar las instituciones (no sube change_seq).
    seqs = {n: i.change_seq for n, i in rows.items()}
    await seed_demo(env.ctx)
    async with env.ctx.sessionmaker() as s:
        again = {i.name: i.change_seq for i in (await s.execute(select(Institution))).scalars()}
    assert again == seqs


async def test_set_institution_ref_command(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    from uno.cli import app
    from uno.config import get_settings

    token = await rep_token(env)
    inst_id = uuid7()
    d_ev, _ = doctor_event(env, institution={"id": str(inst_id), "name": "Hospital Uno"})
    await post_sync(env, token, [d_ev])
    cursor = (await get_state(env, token))["cursor"]

    monkeypatch.setenv("UNO_DATABASE_URL", env.settings.database_url)
    get_settings.cache_clear()
    runner = CliRunner()
    try:
        # asyncio.run (que usa la CLI) no puede correr dentro del bucle de la prueba.
        async def cli(*args: str) -> Any:
            return await asyncio.to_thread(runner.invoke, app, ["set-institution-ref", *args])

        ok = await cli(
            "--name", "hospital uno", "--lat", "4.65", "--lng", "-74.08", "--radius", "250"
        )
        assert ok.exit_code == 0, ok.output
        assert "Hospital Uno" in ok.output

        by_id = await cli("--id", str(inst_id), "--lat", "4.66", "--lng", "-74.09")
        assert by_id.exit_code == 0, by_id.output

        for args in (
            ("--name", "No existe", "--lat", "4.6", "--lng", "-74"),
            ("--lat", "4.6", "--lng", "-74"),  # falta institución
            ("--name", "Hospital Uno", "--id", str(inst_id), "--lat", "4.6", "--lng", "-74"),
            ("--name", "Hospital Uno", "--lat", "95", "--lng", "-74"),
            ("--name", "Hospital Uno", "--lat", "4.6", "--lng", "-74", "--radius", "0"),
            ("--id", "no-uuid", "--lat", "4.6", "--lng", "-74"),
        ):
            bad = await cli(*args)
            assert bad.exit_code != 0, args
    finally:
        get_settings.cache_clear()

    async with env.ctx.sessionmaker() as s:
        inst = await s.get(Institution, inst_id)
    assert inst is not None
    assert (inst.lat, inst.lng) == (4.66, -74.09)
    assert inst.radius_m == 250  # el segundo comando no pasó --radius: se conserva
    assert inst.ref_source == "manual"

    # Sube change_seq: el teléfono la baja en la siguiente sincronización.
    delta = await get_state(env, token, cursor)
    (out,) = delta["institutions"]
    assert (out["lat"], out["lng"], out["radius_m"]) == (4.66, -74.09, 250)
