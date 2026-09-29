"""Constructores de eventos y llamadas de sincronización para las pruebas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from uno import clock
from uno.ids import uuid7

from .conftest import Env, bearer


def ev(
    type_: str,
    payload: dict[str, Any],
    *,
    visit_id: uuid.UUID | None = None,
    ts: datetime | None = None,
    event_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return {
        "event_id": str(event_id or uuid7()),
        "type": type_,
        "visit_id": str(visit_id) if visit_id else None,
        "device_ts": (ts or clock.now()).isoformat(),
        "app_version": "test",
        "payload": payload,
    }


def doctor_event(
    env: Env,
    *,
    doctor_id: uuid.UUID | None = None,
    name: str = "Dra. Laura Méndez",
    line: str = "GASTRU",
    institution: dict[str, Any] | None = None,
    ts: datetime | None = None,
    event_id: uuid.UUID | None = None,
) -> tuple[dict[str, Any], uuid.UUID]:
    doctor_id = doctor_id or uuid7()
    payload: dict[str, Any] = {
        "doctor_id": str(doctor_id),
        "full_name": name,
        "specialty": "Medicina Interna",
        "default_line_id": str(env.lines[line]),
        "institution": institution
        or {"id": str(uuid7()), "name": "Clínica Central", "city": "Bogotá"},
    }
    return ev("doctor_created", payload, ts=ts, event_id=event_id), doctor_id


def visit_event(
    env: Env,
    *,
    doctor_id: uuid.UUID,
    scheduled_at: datetime,
    visit_id: uuid.UUID | None = None,
    line: str = "GASTRU",
    ts: datetime | None = None,
    event_id: uuid.UUID | None = None,
    extra_lines: list[str] | None = None,
) -> tuple[dict[str, Any], uuid.UUID]:
    visit_id = visit_id or uuid7()
    line_ids = [str(env.lines[line])] + [str(env.lines[x]) for x in (extra_lines or [])]
    payload = {
        "doctor_id": str(doctor_id),
        "line_ids": line_ids,
        "scheduled_at": scheduled_at.isoformat(),
    }
    return ev("visit_scheduled", payload, visit_id=visit_id, ts=ts, event_id=event_id), visit_id


def location(
    lat: float,
    lng: float,
    precision_m: float = 10,
    *,
    fix_ts: datetime | None = None,
    source: str = "gps",
) -> dict[str, Any]:
    """Objeto `location` del contrato (lectura de ubicación del teléfono)."""
    return {
        "lat": lat,
        "lng": lng,
        "precision_m": precision_m,
        "fix_ts": (fix_ts or clock.now()).isoformat(),
        "source": source,
    }


def arrived_event(
    visit_id: uuid.UUID,
    loc: dict[str, Any] | None,
    *,
    ts: datetime | None = None,
    event_id: uuid.UUID | None = None,
    **diagnostics: Any,
) -> dict[str, Any]:
    """`visit_arrived`; `diagnostics` = permission, duration_ms, error."""
    return ev(
        "visit_arrived",
        {"location": loc, **diagnostics},
        visit_id=visit_id,
        ts=ts,
        event_id=event_id,
    )


def finished_event(
    visit_id: uuid.UUID,
    loc: dict[str, Any] | None,
    *,
    ts: datetime | None = None,
    event_id: uuid.UUID | None = None,
    **diagnostics: Any,
) -> dict[str, Any]:
    """`visit_finished`; `diagnostics` = permission, duration_ms, error."""
    return ev(
        "visit_finished",
        {"location": loc, **diagnostics},
        visit_id=visit_id,
        ts=ts,
        event_id=event_id,
    )


def retry_event(
    visit_id: uuid.UUID,
    moment: str,
    loc: dict[str, Any] | None,
    *,
    ts: datetime | None = None,
    event_id: uuid.UUID | None = None,
    **diagnostics: Any,
) -> dict[str, Any]:
    """`visit_location_retried`; `moment` = "arrival" | "finish"."""
    return ev(
        "visit_location_retried",
        {"moment": moment, "location": loc, **diagnostics},
        visit_id=visit_id,
        ts=ts,
        event_id=event_id,
    )


async def set_institution_reference(
    env: Env,
    institution_id: uuid.UUID,
    lat: float | None,
    lng: float | None,
    radius_m: int | None = None,
) -> None:
    """Fija (o quita, con None) la referencia de una institución directamente en la base."""
    from uno.modules.catalog.models import Institution

    async with env.ctx.sessionmaker() as session:
        inst = await session.get(Institution, institution_id)
        assert inst is not None
        inst.lat, inst.lng = lat, lng
        if radius_m is not None:
            inst.radius_m = radius_m
        await session.commit()


async def post_sync(
    env: Env,
    token: str,
    events: list[dict[str, Any]],
    *,
    device_id: uuid.UUID | None = None,
    sent_at: datetime | None = None,
    expect: int = 200,
) -> dict[str, Any]:
    r = await env.client.post(
        "/v1/sync",
        headers=bearer(token),
        json={
            "device_id": str(device_id or uuid.UUID(int=1)),
            "sent_at": (sent_at or clock.now()).isoformat(),
            "outbox_pending": len(events),
            "events": events,
        },
    )
    assert r.status_code == expect, r.text
    return r.json()


async def get_state(env: Env, token: str, cursor: int | None = None) -> dict[str, Any]:
    params = {} if cursor is None else {"cursor": cursor}
    r = await env.client.get("/v1/me/state", headers=bearer(token), params=params)
    assert r.status_code == 200, r.text
    return r.json()
