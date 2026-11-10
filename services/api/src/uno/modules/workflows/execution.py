from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Literal

from pydantic import AwareDatetime, Field

from uno import clock, events
from uno.db import next_change_seq
from uno.errors import ApiError
from uno.modules.agenda.models import Visit
from uno.modules.territory.models import PharmacyVisit, RoutePlan
from uno.modules.territory.schemas import Strict
from uno.modules.territory.service import ZONE, enqueue, owner, version

from .models import RouteIncident


class IncidentInput(Strict):
    plan_id: uuid.UUID
    kind: Literal["delay", "cancel", "not_attended"]
    visit_id: uuid.UUID | None = None
    resume_at: AwareDatetime | None = None
    reason: str = Field(min_length=5, max_length=1000)


async def incident(session, actor, command):
    p = IncidentInput.model_validate(command.payload)
    plan = await session.get(RoutePlan, p.plan_id)
    if plan is None:
        raise ApiError(404, "missing_plan", "No encontramos la ruta")
    owner(actor, plan.representative_id)
    version(plan, command.expected_version)
    if plan.status != "published":
        raise ApiError(
            409, "plan_changed", "La ruta cambió. Actualiza antes de registrar la novedad"
        )
    now = clock.now()
    if plan.day != now.astimezone(ZONE).date():
        raise ApiError(422, "wrong_day", "Registra novedades en la ruta de hoy")
    if p.kind == "delay":
        if (
            p.resume_at is None
            or p.resume_at < now - timedelta(hours=4)
            or p.resume_at > now + timedelta(hours=3)
        ):
            raise ApiError(422, "resume_time", "Indica cuándo puedes continuar (máximo tres horas)")
        if p.resume_at.astimezone(ZONE).date() != plan.day:
            raise ApiError(422, "resume_day", "La demora debe pertenecer a esta jornada")
    else:
        stop = next((s for s in plan.stops if s.get("visit_id") == str(p.visit_id)), None)
        if not stop:
            raise ApiError(422, "stop_missing", "Selecciona una visita de la ruta publicada")
        if stop["kind"] == "marketing":
            raise ApiError(422, "marketing_activity", "Abre Mercadeo para reprogramar o cancelar esta actividad")
        model = Visit if stop["kind"] == "doctor" else PharmacyVisit
        visit = await session.get(model, p.visit_id)
        if (
            not visit
            or visit.representative_id != plan.representative_id
            or visit.status != "scheduled"
        ):
            raise ApiError(
                409,
                "visit_started",
                "La visita ya cambió o está iniciada. Usa su pantalla para finalizarla",
            )
        visit.status, visit.updated_at = "not_done", now
        if stop["kind"] == "doctor":
            visit.not_done_reason = (
                "doctor_unavailable" if p.kind == "not_attended" else "cancelled_by_office"
            )
            visit.change_seq = await next_change_seq(session)
        else:
            visit.report = {**(visit.report or {}), "not_done_reason": p.reason}
            visit.version += 1
        await events.emit(
            session,
            event_type="visit_not_done" if model is Visit else "pharmacy_visit_not_done",
            occurred_at=now,
            recorded_at=now,
            actor_type="user",
            actor_id=actor.id,
            entities={"visit_id": visit.id, "representative_id": plan.representative_id},
            payload={"reason": p.kind},
            correlation_id=visit.id,
        )
    session.add(
        RouteIncident(
            id=command.id,
            representative_id=plan.representative_id,
            plan_id=plan.id,
            day=plan.day,
            kind=p.kind,
            resume_at=p.resume_at if p.kind == "delay" else None,
            reason=p.reason.strip(),
            visit_id=p.visit_id,
            actor_id=actor.id,
            created_at=now,
        )
    )
    job = await enqueue(
        session, plan.representative_id, plan.day, f"incident:{command.id}", plan.max_contacts
    )
    return {"id": str(command.id), "job_id": str(job.id), "status": "queued"}


def plan_changes(previous, stops):
    old = {s["key"]: s for s in previous.stops} if previous else {}
    new = {s["key"]: s for s in stops}
    changes = []
    for key in old.keys() | new.keys():
        a, b = old.get(key), new.get(key)
        if a is None:
            changes.append({"kind": "added", "label": b["label"], "to": b.get("arrival_at")})
        elif b is None:
            changes.append({"kind": "removed", "label": a["label"], "from": a.get("arrival_at")})
        elif not b.get("locked") and a.get("arrival_at") != b.get("arrival_at"):
            changes.append(
                {
                    "kind": "moved",
                    "label": b["label"],
                    "from": a.get("arrival_at"),
                    "to": b.get("arrival_at"),
                }
            )
    return sorted(changes, key=lambda x: x["label"])
