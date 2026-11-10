"""Authenticated browser voice sessions, attached to the existing call/report pipeline."""
from datetime import timedelta
import uuid

import httpx
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func

from uno import clock
from uno.db import next_change_seq
from uno.deps import get_ctx, get_current_user
from uno.errors import ApiError
from uno.modules.agenda.models import Visit
from uno.modules.auth.models import User
from uno.modules.calls import service
from uno.modules.calls.brands import catalogue
from uno.modules.calls.context import build_dynamic_variables
from uno.modules.calls.models import Call, CallVisit, VisitReport
from uno.modules.calls.provider import parse_conversation

router = APIRouter(prefix="/v1/territory/browser-voice", tags=["browser-voice"])


class Start(BaseModel):
    visit_id: uuid.UUID


class Bind(BaseModel):
    conversation_id: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


async def provider_get(ctx, path, params=None):
    settings = ctx.settings
    if not settings.elevenlabs_api_key or not settings.elevenlabs_agent_id:
        raise ApiError(503, "voice_unavailable", "La voz todavía no está configurada")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.get(settings.elevenlabs_base_url.rstrip('/') + path,
                headers={"xi-api-key": settings.elevenlabs_api_key}, params=params)
        result.raise_for_status()
        return result.json()
    except (httpx.HTTPError, ValueError):
        raise ApiError(503, "voice_unavailable", "No pudimos conectar con UNO. Intenta de nuevo; tu visita sigue guardada.") from None


@router.post("/start")
async def start(body: Start, response: Response, actor=Depends(get_current_user), ctx=Depends(get_ctx)):
    response.headers['Cache-Control'] = 'no-store'
    if actor.role != 'rep':
        raise ApiError(403, "representative_required", "La entrevista pertenece al visitador")
    now = clock.now()
    async with ctx.sessionmaker() as session:
        # Serialize browser starts across different visits for the same person.
        await session.scalar(select(User).where(User.id == actor.id).with_for_update())
        visit = await session.scalar(select(Visit).where(Visit.id == body.visit_id,
            Visit.representative_id == actor.id).with_for_update())
        if not visit:
            raise ApiError(404, "missing_visit", "No encontramos tu visita")
        if not visit.finished_at:
            raise ApiError(409, "finish_first", "Primero registra la llegada y termina la visita")
        report = await session.get(VisitReport, visit.id)
        if report and report.status == 'confirmed':
            raise ApiError(409, "already_confirmed", "El reporte ya está confirmado. Puedes consultarlo abajo.")
        live = (await session.execute(select(Call, CallVisit).join(CallVisit, CallVisit.call_id == Call.id)
            .where(CallVisit.visit_id == visit.id, CallVisit.live.is_(True)).with_for_update())).all()
        for call, link in live:
            if call.status == 'dialing':
                raise ApiError(409, "voice_active", "Ya hay una conversación iniciada. Termínala o recupera su reporte.")
            call.status = 'cancelled'
            call.updated_at = now
            link.live = False
        active = await session.scalar(select(Call.id).where(Call.representative_id == actor.id,
            Call.status == 'dialing'))
        if active:
            raise ApiError(409, "voice_active", "Termina la otra conversación antes de abrir esta visita.")
        count = await session.scalar(select(func.count()).select_from(Call).where(
            Call.representative_id == actor.id, Call.provider == 'elevenlabs_browser',
            Call.created_at > now-timedelta(hours=1)))
        if count >= 10:
            raise ApiError(429, "voice_limit", "Alcanzaste diez entrevistas en una hora. Puedes completar el reporte por escrito.")
        config = await provider_get(ctx, '/v1/convai/agents/' + ctx.settings.elevenlabs_agent_id)
        cap = config.get('conversation_config', {}).get('conversation', {}).get('max_duration_seconds', 0)
        if not 0 < cap <= 300:
            raise ApiError(503, "voice_duration", "El agente necesita un límite de cinco minutos antes de iniciar.")
        signed = await provider_get(ctx, '/v1/convai/conversation/get-signed-url',
            {'agent_id': ctx.settings.elevenlabs_agent_id})
        call = Call(representative_id=actor.id, direction='inbound', purpose='summary',
            provider='elevenlabs_browser', status='dialing', attempt=1, scheduled_for=now,
            dialed_at=now, created_at=now, updated_at=now)
        session.add(call)
        await session.flush()
        session.add(CallVisit(call_id=call.id, visit_id=visit.id, position=1, live=True))
        await session.flush()
        briefs = await service._briefs(session, call.id)
        variables = build_dynamic_variables(actor.full_name, briefs, tz_name=actor.timezone,
            include_names=ctx.settings.call_include_doctor_names, now=now)
        variables['catalogo_snc'] = ', '.join(p['name'] for p in await catalogue(session, [visit.primary_line_id]))
        if visit.planned_by == 'demo':
            variables['visitas_texto'] += '\nEscenario de demostración de Novamed. Registrar únicamente lo que relata el visitador.'
        visit.report_mode = 'browser'
        visit.status = 'in_call'
        visit.updated_at = now
        visit.change_seq = await next_change_seq(session)
        await session.commit()
        return {'call_id': str(call.id), 'signed_url': signed['signed_url'],
            'dynamic_variables': variables, 'user_id': str(call.id), 'max_duration_seconds': cap}


async def own_call(ctx, actor, id):
    async with ctx.sessionmaker() as session:
        call = await session.scalar(select(Call).where(Call.id == id,
            Call.representative_id == actor.id, Call.provider == 'elevenlabs_browser'))
        if not call:
            raise ApiError(404, 'missing_call', 'No encontramos tu conversación')
        return call


@router.post("/{id}/bind")
async def bind(id: uuid.UUID, body: Bind, actor=Depends(get_current_user), ctx=Depends(get_ctx)):
    call = await own_call(ctx, actor, id)
    data = await provider_get(ctx, '/v1/convai/conversations/' + body.conversation_id)
    client_data = data.get('conversation_initiation_client_data') or {}
    user_id = data.get('user_id') or client_data.get('user_id')
    if data.get('agent_id') != ctx.settings.elevenlabs_agent_id or user_id != str(id):
        raise ApiError(403, 'conversation_mismatch', 'La conversación no corresponde a esta visita')
    async with ctx.sessionmaker() as session:
        saved = await session.scalar(select(Call).where(Call.id == id).with_for_update())
        if saved.provider_conversation_id and saved.provider_conversation_id != body.conversation_id:
            raise ApiError(409, 'already_bound', 'Esta visita ya tiene otra conversación')
        saved.provider_conversation_id = body.conversation_id
        saved.updated_at = clock.now()
        await session.commit()
    if data.get('status') in ('done', 'failed'):
        await service.handle_result(ctx, id, parse_conversation(data), clock.now())
    return {'bound': True}


@router.get("/{id}")
async def status(id: uuid.UUID, response: Response, actor=Depends(get_current_user), ctx=Depends(get_ctx)):
    response.headers['Cache-Control'] = 'no-store'
    call = await own_call(ctx, actor, id)
    if call.status == 'dialing' and call.provider_conversation_id:
        data = await provider_get(ctx, '/v1/convai/conversations/' + call.provider_conversation_id)
        if data.get('status') in ('done', 'failed'):
            await service.handle_result(ctx, id, parse_conversation(data), clock.now())
            call = await own_call(ctx, actor, id)
    async with ctx.sessionmaker() as session:
        report = await session.scalar(select(VisitReport).where(VisitReport.call_id == id))
        return {'call_id': str(id), 'status': call.status, 'duration_s': call.duration_s,
            'report_saved': report is not None, 'report_status': report.status if report else None,
            'failure_reason': call.failure_reason}


@router.post("/{id}/cancel")
async def cancel(id: uuid.UUID, actor=Depends(get_current_user), ctx=Depends(get_ctx)):
    await own_call(ctx, actor, id)
    async with ctx.sessionmaker() as session:
        call = await session.scalar(select(Call).where(Call.id == id).with_for_update())
        if call.status == 'dialing' and not call.provider_conversation_id:
            call.status = 'cancelled'
            call.updated_at = clock.now()
            for link, visit in await service._call_visits(session, id):
                link.live = False
                if visit.status == 'in_call':
                    await service._set_visit(session, visit, 'finished', clock.now())
            await session.commit()
    return {'ok': True}
