from __future__ import annotations

import asyncio
import csv
import io
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from uno import clock
from uno.deps import get_ctx, get_current_user, get_session
from uno.errors import ApiError
from uno.modules.auth.permissions import require_capability, require_representative
from uno.modules.journey.provider import ProviderUnavailable
from uno.modules.territory.service import ZONE

from . import dashboard, service
from .models import MarketingActivity, MarketingRevision

router = APIRouter(prefix="/v1/territory", tags=["marketing-management"])


@router.get("/marketing/catalog")
async def catalog(
    representative_id: uuid.UUID | None = None,
    actor=Depends(get_current_user),
    session=Depends(get_session),
):
    return await service.catalog(session, actor, representative_id)


@router.get("/marketing/activities")
async def activities(
    response: Response,
    representative_id: uuid.UUID | None = None,
    status: str = "all",
    q: str = Query(default="", max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=12, ge=1, le=50),
    actor=Depends(get_current_user),
    session=Depends(get_session),
):
    query = service.scope(select(MarketingActivity), actor)
    if representative_id:
        require_representative(actor, representative_id)
        query = query.where(MarketingActivity.representative_id == representative_id)
    if status != "all":
        query = query.where(MarketingActivity.status == status)
    if q.strip():
        from uno.modules.catalog.models import Institution

        query = query.join(Institution).where(
            (MarketingActivity.objective.icontains(q.strip(), autoescape=True))
            | Institution.name.icontains(q.strip(), autoescape=True)
        )
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await session.scalars(
            query.order_by(MarketingActivity.starts_at.desc()).offset(offset).limit(limit)
        )
    ).all()
    response.headers["Cache-Control"] = "private, no-store"
    return {"total": total, "items": [await service.render(session, r) for r in rows]}


@router.get("/marketing/activities/{id}")
async def activity(id: uuid.UUID, actor=Depends(get_current_user), session=Depends(get_session)):
    row = await service.get_activity(session, actor, id)
    result = await service.render(session, row)
    revisions = (
        await session.scalars(
            select(MarketingRevision)
            .where(MarketingRevision.activity_id == id)
            .order_by(MarketingRevision.version)
        )
    ).all()
    result["history"] = [
        {"version": r.version, "at": r.created_at.isoformat(), "status": r.snapshot["status"]}
        for r in revisions
    ]
    return result


@router.get("/dashboard")
async def overview(
    response: Response,
    start: date | None = None,
    end: date | None = None,
    representative_id: uuid.UUID | None = None,
    demo: bool = False,
    actor=Depends(get_current_user),
    session=Depends(get_session),
):
    today = clock.now().astimezone(ZONE).date()
    response.headers["Cache-Control"] = "private, no-store"
    data = await dashboard.snapshot(
        session, actor, start or today - timedelta(days=6), end or today, representative_id, demo=demo
    )
    from .reference import snapshot as reference_snapshot
    data['reference'] = await reference_snapshot(session,actor)
    return data


class Question(BaseModel):
    question: str = Field(min_length=5, max_length=1000)
    start: date
    end: date
    representative_id: uuid.UUID | None = None
    demo: bool = False


@router.post("/dashboard/ask")
async def ask(
    body: Question,
    actor=Depends(get_current_user),
    session=Depends(get_session),
    ctx=Depends(get_ctx),
):
    require_capability(actor, "dashboard.read")
    snapshot = await dashboard.snapshot(
        session, actor, body.start, body.end, body.representative_id, demo=body.demo
    )
    provider = ctx.recommendations_provider
    from .insights import answer_from_metrics
    from .commercial import summary as commercial_summary
    commercial = await commercial_summary(session, actor) if actor.management_profile == "line" else None
    if provider is None:
        return answer_from_metrics(snapshot, body.question, commercial)
    # Recompute scope on the server. Only authorized aggregates and short confirmed
    # report excerpts are sent; never raw call transcripts or attendee lists.
    context = {
        k: snapshot[k]
        for k in ("as_of", "start", "end", "counts", "team", "products", "sources", "definitions")
    }
    context["scope"] = (
        "Tablero del equipo SNC autorizado. Las recomendaciones son sugerencias; "
        "no cambias datos ni infieres ventas o prescripción. "
        "Responde sobre los indicadores del período y cita su nombre."
    )
    context["performance"] = {k:snapshot["performance"][k] for k in ("brands","barriers","voice","frequency","definitions")}
    context["performance"]["frequency"] = {k:v for k,v in context["performance"]["frequency"].items() if k != "actionable"}
    context["mode"] = snapshot["mode"]
    from .reference import snapshot as reference_snapshot
    reference=await reference_snapshot(session,actor)
    context['real_imported_context']={k:reference[k] for k in ('doctors','active_contacts','verified_sites','pharmacies','team','specialties')}
    context["intelligence"] = snapshot["intelligence"]["baseline"]
    context["recent_confirmed_reports"] = snapshot["recent_confirmed_reports"]
    context["performance"]["barriers"] = [{**b,"text":b["text"][:160]} for b in context["performance"]["barriers"][:8]]
    # Source cuts are aggregate-only, line-manager scoped and explicitly dated.
    if commercial is not None:
        context["commercial"] = {"series":commercial["series"][:12],"note":commercial["note"],"sample_of_series":len(commercial["series"])}
    import json
    while len(json.dumps(context,ensure_ascii=False)) > 11000 and context.get("commercial",{}).get("series"):
        context["commercial"]["series"].pop()
    while len(json.dumps(context,ensure_ascii=False)) > 11000 and context["recent_confirmed_reports"]:
        context["recent_confirmed_reports"].pop()
    try:
        answer = await asyncio.wait_for(
            provider.respond(context=context, history=[], question=body.question), timeout=12
        )
    except (ProviderUnavailable, TimeoutError):
        return answer_from_metrics(snapshot, body.question, commercial)
    return {
        "answer": answer,
        "as_of": snapshot["as_of"],
        "sources": ["Visitas y reportes", "Actividades de mercadeo", "Panel y compromisos"],
        "changes_made": False,
        "mode": "generative",
    }


@router.get("/dashboard/report.pdf")
async def report_pdf(start: date, end: date, representative_id: uuid.UUID | None = None,
                     demo: bool = False, actor=Depends(get_current_user), session=Depends(get_session)):
    data = await dashboard.snapshot(session, actor, start, end, representative_id, demo=demo)
    from .pdf_report import generate
    from .commercial import summary as commercial_summary
    commercial = await commercial_summary(session, actor) if actor.management_profile == "line" else None
    from .reference import snapshot as reference_snapshot
    data['reference']=await reference_snapshot(session,actor)
    content = await asyncio.to_thread(generate, data, actor.full_name, commercial)
    return Response(content,media_type="application/pdf",headers={
        "Cache-Control":"private, no-store", "Content-Disposition":f'attachment; filename="VisiMed-SNC-{start}-{end}.pdf"'})


@router.get('/source-files')
async def source_files(actor=Depends(get_current_user)):
    from .source_files import listing
    return {'documents':listing(actor),'note':'Originales completos. El análisis operativo utiliza únicamente el alcance autorizado del piloto SNC en Bogotá.'}


@router.get('/source-files/{id}')
async def source_file(id:str,actor=Depends(get_current_user)):
    from .source_files import get
    from fastapi.responses import FileResponse
    row,path=get(actor,id)
    return FileResponse(path,filename=row['filename'],headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@router.get("/marketing/export")
async def export(
    start: date,
    end: date,
    representative_id: uuid.UUID | None = None,
    actor=Depends(get_current_user),
    session=Depends(get_session),
):
    lower, upper = dashboard.date_bounds(start, end)
    query = service.scope(
        select(MarketingActivity).where(
            MarketingActivity.starts_at >= lower, MarketingActivity.starts_at < upper
        ),
        actor,
    )
    if representative_id:
        require_representative(actor, representative_id)
        query = query.where(MarketingActivity.representative_id == representative_id)
    rows = (await session.scalars(query.order_by(MarketingActivity.starts_at))).all()
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(
        [
            "ID",
            "Versión",
            "Fecha Bogotá",
            "Visitador",
            "Institución",
            "Tipo",
            "Estado",
            "Objetivo",
            "Marcas",
            "Consulta",
            "Asistentes panel",
            "Asistentes externos",
            "Especialidades",
            "Material entregado",
            "Resultado",
            "Siguiente acción",
            "Pharmadvisor",
        ]
    )

    def safe(value):
        text = str(value)
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text

    for row in rows:
        r = await service.render(session, row)
        d = row.data
        attendees = d.get("attendees", []) if row.status == "completed" else []
        writer.writerow(
            [
                safe(x)
                for x in [
                    row.id,
                    row.version,
                    row.starts_at.astimezone(ZONE).isoformat(),
                    r["representative"],
                    r["institution"],
                    r["kind_label"],
                    row.status,
                    row.objective,
                    ", ".join(p["name"] for p in d.get("products", [])),
                    ", ".join(d.get("consultation_types", [])),
                    " | ".join(a["name"] for a in attendees if a.get("doctor_id")),
                    " | ".join(a["name"] for a in attendees if not a.get("doctor_id")),
                    " | ".join(f"{k}: {v}" for k, v in r["specialties"].items())
                    if row.status == "completed"
                    else "",
                    " | ".join(f"{m['name']}: {m['quantity']}" for m in d.get("materials", []))
                    if row.status == "completed"
                    else "",
                    d.get("outcome", "") if row.status == "completed" else "",
                    d.get("next_action", ""),
                    "No enviado; conciliar manualmente",
                ]
            ]
        )
    return {
        "filename": f"mercadeo-{start}-{end}.csv",
        "content": "\ufeff" + stream.getvalue(),
        "rows": len(rows),
        "pharmadvisor_sent": False,
    }


@router.get("/commercial")
async def commercial_status(actor=Depends(get_current_user), session=Depends(get_session)):
    from .commercial import summary
    return await summary(session, actor)


@router.post("/commercial/preview")
async def commercial_preview(request: Request, filename: str, source: str, actor=Depends(get_current_user), session=Depends(get_session)):
    from .commercial import allowed, preview
    allowed(actor)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 20 * 1024 * 1024:
            from uno.errors import ApiError
            raise ApiError(413, "too_large", "Usa un CSV de hasta 20 MB")
    result = await preview(session, actor, filename, source, bytes(raw))
    await session.commit()
    return result
