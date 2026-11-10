from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from uno.context import AppContext
from uno.deps import get_ctx, get_current_user, get_session
from uno.errors import ApiError
from uno.modules.auth.models import User

from . import providers, service
from .models import RoutePlan
from .schemas import Command

router = APIRouter(prefix="/v1/territory", tags=["territory"])


@router.get("/visit-reports/{id}")
async def visit_report(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_current_user),
):
    from uno.modules.agenda.models import Visit
    from uno.modules.calls.models import Call, CallVisit, VisitReport
    from sqlalchemy import select
    from uno.modules.calls.snc_report import SNCReport
    from uno.modules.catalog.models import Doctor
    visit = await session.get(Visit, id)
    if not visit:
        raise ApiError(404, "not_found", "No se encontró la visita")
    from uno.modules.auth.permissions import require_visit_read
    require_visit_read(actor, visit)
    from uno.modules.auth.permissions import line_ids
    scope = line_ids(actor)
    if scope is not None and visit.primary_line_id not in scope:
        raise ApiError(403, "out_of_scope", "La visita no pertenece a tu línea")
    report = await session.get(VisitReport, id)
    doctor = await session.get(Doctor, visit.doctor_id)
    call = await session.get(Call, report.call_id) if report and report.call_id else None
    if call is None:
        call = await session.scalar(select(Call).join(CallVisit).where(CallVisit.visit_id == id).order_by(Call.created_at.desc()).limit(1))
    raw = (report.fields or {}).get("snc_report_json", {}).get("value") if report else None
    structured = SNCReport.model_validate_json(raw) if raw else None
    from uno.modules.calls.brands import catalogue, review
    brands = await catalogue(session, [visit.primary_line_id])
    brand_issues = review(raw, brands)[1] if raw else []
    return {
        "visit_id": id, "doctor": doctor.full_name if doctor else "Visita",
        "editable": actor.id == visit.representative_id and bool(report or visit.status in ("finished", "in_call", "processing", "ready", "no_interview", "error")),
        "visit_finished": bool(visit.finished_at or report),
        "status": report.status if report else visit.status,
        "version": report.change_seq if report else 0,
        "agent_version": report.extractor_version if report else None,
        "structured": structured.model_dump(mode="json") if structured else None,
        "missing": (structured.missing() if structured else []) + [x["message"] for x in brand_issues],
        "catalogue": brands, "brand_issues": brand_issues,
        "fields": report.fields if report else {},
        "duration_s": call.duration_s if call else None,
        "call_status": call.status if call else None,
        "call_failure_reason": call.failure_reason if call else None,
        "transcript": (call.transcript or []) if call else [],
        "report_due_at": visit.report_due_at,
        "pending_since": visit.report_pending_at,
    }


@router.get("/state")
async def state(
    representative_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_current_user),
    ctx: AppContext = Depends(get_ctx),
):
    data = await service.snapshot(session, actor, representative_id)
    data["providers"] = {
        "roads_configured": bool(ctx.settings.territory_osrm_url),
        "geocoder_configured": bool(ctx.settings.territory_geocoder_url),
    }
    return data


@router.post("/commands")
async def command(
    body: Command,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_current_user),
    ctx: AppContext = Depends(get_ctx),
):
    try:
        return await service.execute(session, actor, body, ctx)
    except ValidationError as exc:
        await session.rollback()
        raise ApiError(
            422,
            "invalid_input",
            "; ".join(e["msg"] for e in exc.errors(include_input=False))[:1000],
        ) from None


@router.get("/geocode")
async def geocode(
    q: str = Query(min_length=5, max_length=240),
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_current_user),
    ctx: AppContext = Depends(get_ctx),
):
    return await providers.geocode(ctx.settings, session, q)


@router.get("/routes/{id}/geometry")
async def geometry(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_current_user),
    ctx: AppContext = Depends(get_ctx),
):
    plan = await session.get(RoutePlan, id)
    if not plan:
        raise ApiError(404, "not_found", "No se encontró la ruta")
    service.owner(actor, plan.representative_id)
    # A recalculated plan starts at the latest field location. Do not draw a
    # detour back through completed stops that are retained only as history.
    points = [
        (x["lat"], x["lng"]) for x in plan.stops if x.get("lat") is not None and not x.get("locked")
    ]
    origin = plan.metrics.get("origin")
    if origin:
        points.insert(0, (origin["lat"], origin["lng"]))
    if origin and plan.metrics.get("return_to_origin"):
        destination = plan.metrics.get("destination") or origin
        points.append((destination["lat"], destination["lng"]))
    return await providers.road_geometry(ctx.settings, points)
