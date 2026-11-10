from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import defer

from uno.deps import get_current_user, get_session, get_ctx
from uno.modules.journey.schema import QuestionIn
from uno.errors import ApiError
from uno.modules.agenda.models import Visit
from uno.modules.auth.permissions import line_ids, permits, require_capability
from uno.modules.catalog.models import Doctor
from uno.modules.territory.service import owner

from .knowledge import MAX_FILE, document_json, get_document, import_document, retrieve
from .models import KnowledgeDocument
from .tasks import list_tasks, pending_for_visit

router = APIRouter(prefix="/v1/territory", tags=["workflows"])


@router.get("/tasks")
async def tasks(
    representative_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
    actor=Depends(get_current_user),
    session=Depends(get_session),
):
    return {"tasks": await list_tasks(session, actor, representative_id or actor.id, doctor_id)}


@router.get("/visit-brief/{id}")
async def brief(id: uuid.UUID, actor=Depends(get_current_user), session=Depends(get_session)):
    from uno.modules.journey.service import preparation_context

    visit = await session.get(Visit, id)
    if not visit:
        raise ApiError(404, "missing_visit", "No encontramos la visita")
    owner(actor, visit.representative_id)
    allowed = line_ids(actor)
    if allowed is not None and visit.primary_line_id not in allowed:
        raise ApiError(403, "out_of_scope", "La visita no pertenece a tu línea")
    doctor = await session.get(Doctor, visit.doctor_id)
    context = await preparation_context(session, visit)
    query = context.get("objective") or context["context"].get("barrier") or ""
    return {
        "visit_id": str(id),
        "doctor": doctor.full_name,
        "context": context,
        "tasks": await pending_for_visit(session, visit),
        "sources": await retrieve(session, actor, query, visit.primary_line_id),
    }


@router.get("/library")
async def library(actor=Depends(get_current_user), session=Depends(get_session)):
    query = select(KnowledgeDocument).options(defer(KnowledgeDocument.original))
    allowed = line_ids(actor)
    if allowed is not None:
        query = query.where(KnowledgeDocument.line_id.in_(allowed))
    manage = permits(actor, "knowledge.manage")
    if not manage:
        query = query.where(KnowledgeDocument.status == "approved")
    rows = (
        await session.scalars(
            query.order_by(KnowledgeDocument.title, KnowledgeDocument.version.desc())
        )
    ).all()
    return {"can_manage": manage, "documents": [document_json(r) for r in rows]}


@router.get("/library/search")
async def search(
    q: str = Query(min_length=2, max_length=500),
    actor=Depends(get_current_user),
    session=Depends(get_session),
):
    hits = await retrieve(session, actor, q)
    return {
        "sources": hits,
        "status": "found" if hits else "insufficient_material",
        "message": "Fragmentos del material aprobado; revisa la diapositiva completa."
        if hits
        else "El material aprobado no permite responder esta consulta.",
    }


@router.post("/library/import")
async def upload(
    request: Request,
    filename: str,
    line_id: uuid.UUID,
    actor=Depends(get_current_user),
    session=Depends(get_session),
):
    require_capability(actor, "knowledge.manage")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_FILE:
            raise ApiError(413, "too_large", "El máximo es 20 MB")
    row = await import_document(session, actor, filename, line_id, bytes(raw))
    await session.commit()
    return document_json(row)


@router.get("/library/{id}")
async def document(id: uuid.UUID, actor=Depends(get_current_user), session=Depends(get_session)):
    return document_json(await get_document(session, actor, id), detail=True)


@router.get("/library/{id}/original")
async def original(id: uuid.UUID, actor=Depends(get_current_user), session=Depends(get_session)):
    row = await get_document(session, actor, id)
    raw = await session.scalar(select(KnowledgeDocument.original).where(KnowledgeDocument.id == id))
    return Response(
        raw,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(row.filename)}",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/learning/{id}")
async def learning_context(id: uuid.UUID, actor=Depends(get_current_user), session=Depends(get_session)):
    from .learning import context
    return await context(session, actor, id)


@router.post('/learning/{id}/ask')
async def learning_question(id:uuid.UUID,body:QuestionIn,actor=Depends(get_current_user),session=Depends(get_session),ctx=Depends(get_ctx)):
    from .learning import own_visit
    from uno.modules.journey.service import answer_question
    from uno import clock
    visit=await own_visit(session,actor,id,write=True)
    return await answer_question(session,ctx,actor,visit,body,clock.now(),learning_mode=True)
