from __future__ import annotations

import hashlib
import uuid
from datetime import date
from typing import Literal

from pydantic import Field
from sqlalchemy import select

from uno import clock, events
from uno.errors import ApiError
from uno.modules.agenda.models import Visit
from uno.modules.calls.snc_report import SNCReport
from uno.modules.catalog.models import Doctor
from uno.modules.territory.schemas import Strict
from uno.modules.territory.service import owner, version

from .models import FollowupTask


async def reconcile_tasks(session, visit, report, now):
    """Project explicit, confirmed commitments. Never infer completion from a new call."""
    if report.status != "confirmed":
        return
    raw = (report.fields or {}).get("snc_report_json", {}).get("value")
    if not raw:
        return  # Legacy unstructured statements remain evidence, not invented tasks.
    data = SNCReport.model_validate_json(raw)
    if data.commitments is None:
        return  # Unknown does not cancel existing commitments.
    current = {
        r.source_key: r
        for r in (
            await session.scalars(select(FollowupTask).where(FollowupTask.visit_id == visit.id))
        ).all()
    }
    wanted = set()
    for item in data.commitments:
        action = item.action.strip()
        key = hashlib.sha256(
            f"{visit.id}:{item.owner}:{' '.join(action.casefold().split())}".encode()
        ).hexdigest()
        if key in wanted:
            continue
        wanted.add(key)
        row = current.get(key)
        if row is None:
            session.add(
                FollowupTask(
                    source_key=key,
                    visit_id=visit.id,
                    representative_id=visit.representative_id,
                    owner=item.owner,
                    action=action,
                    due_on=item.due_date,
                    next_objective=item.next_objective,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            changed = False
            if not row.due_manual and row.due_on != item.due_date:
                row.due_on = item.due_date
                changed = True
            if row.next_objective != item.next_objective:
                row.next_objective = item.next_objective
                changed = True
            if row.status == "superseded":
                row.status = "open"
                changed = True
            if changed:
                row.version += 1
                row.updated_at = now
    for key, row in current.items():
        if key not in wanted and row.status in {"open", "in_progress"}:
            row.status = "superseded"
            row.version += 1
            row.updated_at = now


def task_json(row, doctor=None, visit=None):
    from uno.modules.territory.service import ZONE

    today = clock.now().astimezone(ZONE).date()
    return {
        "id": str(row.id),
        "visit_id": str(row.visit_id),
        "representative_id": str(row.representative_id),
        "doctor_id": str(visit.doctor_id) if visit else None,
        "doctor": doctor,
        "owner": row.owner,
        "action": row.action,
        "due_on": row.due_on.isoformat() if row.due_on else None,
        "status": row.status,
        "evidence": row.evidence,
        "next_objective": row.next_objective,
        "version": row.version,
        "updated_at": row.updated_at.isoformat(),
        "overdue": bool(
            row.due_on and row.due_on < today and row.status in {"open", "in_progress"}
        ),
        "due_today": row.due_on == today and row.status in {"open", "in_progress"},
    }


async def list_tasks(session, actor, rep, doctor_id=None):
    from uno.modules.auth.permissions import line_ids

    owner(actor, rep)
    scope = line_ids(actor)
    query = (
        select(FollowupTask, Doctor.full_name, Visit)
        .join(Visit, Visit.id == FollowupTask.visit_id)
        .join(Doctor, Doctor.id == Visit.doctor_id)
        .where(FollowupTask.representative_id == rep)
    )
    if scope is not None:
        query = query.where(Visit.primary_line_id.in_(scope))
    if doctor_id:
        query = query.where(Visit.doctor_id == doctor_id)
    return [
        task_json(r, d, v)
        for r, d, v in (
            await session.execute(query.order_by(FollowupTask.updated_at.desc()).limit(1000))
        ).all()
    ]


class TaskUpdate(Strict):
    id: uuid.UUID
    status: Literal["open", "in_progress", "done", "cancelled"]
    due_on: date | None = None
    owner: Literal["representative", "doctor", "unknown"]
    evidence: str = Field(default="", max_length=2000)


async def update_task(session, actor, command):
    from uno.modules.auth.permissions import line_ids, require_capability

    require_capability(actor, "territory.write")
    p = TaskUpdate.model_validate(command.payload)
    row = await session.get(FollowupTask, p.id)
    if not row:
        raise ApiError(404, "task_missing", "No encontramos el compromiso")
    owner(actor, row.representative_id)
    visit = await session.get(Visit, row.visit_id)
    scope = line_ids(actor)
    if scope is not None and visit.primary_line_id not in scope:
        raise ApiError(403, "out_of_scope", "El compromiso no pertenece a tu línea")
    version(row, command.expected_version)
    if row.status == "superseded":
        raise ApiError(
            409, "task_replaced", "Este compromiso fue reemplazado al corregir el reporte"
        )
    if p.status in {"done", "cancelled"} and len(p.evidence.strip()) < 5:
        raise ApiError(
            422, "evidence_required", "Explica el cumplimiento o el motivo de cancelación"
        )
    before = row.status
    if row.due_on != p.due_on:
        row.due_manual = True
    row.status, row.owner, row.due_on, row.evidence = (
        p.status,
        p.owner,
        p.due_on,
        p.evidence.strip(),
    )
    row.version += 1
    row.updated_at = clock.now()
    await events.emit(
        session,
        event_type="commitment_updated",
        occurred_at=row.updated_at,
        recorded_at=row.updated_at,
        actor_type="user",
        actor_id=actor.id,
        entities={
            "visit_id": row.visit_id,
            "representative_id": row.representative_id,
            "task_id": row.id,
        },
        payload={"previous_status": before, "status": row.status, "version": row.version},
        correlation_id=row.visit_id,
    )
    return {"id": str(row.id), "version": row.version}


async def pending_for_visit(session, visit):
    rows = (
        await session.scalars(
            select(FollowupTask)
            .join(Visit, Visit.id == FollowupTask.visit_id)
            .where(
                FollowupTask.representative_id == visit.representative_id,
                Visit.doctor_id == visit.doctor_id,
                Visit.primary_line_id == visit.primary_line_id,
                FollowupTask.status.in_(["open", "in_progress"]),
            )
            .order_by(FollowupTask.due_on)
            .limit(30)
        )
    ).all()
    return [task_json(r) for r in rows]
