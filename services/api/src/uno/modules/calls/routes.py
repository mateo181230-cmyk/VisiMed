"""Webhook de ElevenLabs: avisa que terminó (o no arrancó) una llamada.

Sin sesión: la **firma HMAC** es la autenticación. ElevenLabs firma ``"{t}.{cuerpo}"`` con el
secreto del webhook y manda ``ElevenLabs-Signature: t=<unix>,v0=<hex>``. Se rechaza una firma
que no coincide y una marca de tiempo de hace más de 30 minutos (repetición de mensajes).

Se responde 200 enseguida: si el endpoint falla, ElevenLabs reintenta y, tras 10 fallos seguidos
sin éxito en 7 días, desactiva el webhook. El resultado también se recoge por consulta directa
(``poll_calls``), así que un webhook perdido no pierde la llamada.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from uno import clock
from uno.context import AppContext
from uno.deps import get_ctx
from uno.modules.calls import service
from uno.modules.calls.provider import parse_conversation

log = logging.getLogger("uno.calls")
router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])

SIGNATURE_TOLERANCE_S = 30 * 60


def sign(secret: str, body: bytes, timestamp: int) -> str:
    """Cabecera ``ElevenLabs-Signature`` para ``body`` (la usan las pruebas y el simulador)."""
    digest = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v0={digest}"


def verify_signature(secret: str, header: str | None, body: bytes, now: datetime) -> bool:
    if not secret or not header:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        timestamp = int(parts["t"])
        received = parts["v0"]
    except (KeyError, ValueError):
        return False
    if abs(int(now.timestamp()) - timestamp) > SIGNATURE_TOLERANCE_S:
        return False
    expected = sign(secret, body, timestamp).split("v0=", 1)[1]
    return hmac.compare_digest(received, expected)


@router.post("/elevenlabs", include_in_schema=True)
async def elevenlabs_webhook(
    request: Request, ctx: AppContext = Depends(get_ctx)
) -> dict[str, Any]:
    body = await request.body()
    now = clock.now()
    secret = ctx.settings.elevenlabs_webhook_secret
    if not secret:
        log.warning("webhook de ElevenLabs recibido sin UNO_ELEVENLABS_WEBHOOK_SECRET configurado")
    if not verify_signature(secret, request.headers.get("elevenlabs-signature"), body, now):
        raise HTTPException(status_code=401, detail="No autorizado")

    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Cuerpo inválido") from None
    kind = payload.get("type")
    data = payload.get("data") or {}
    client_data = (data.get("conversation_initiation_client_data") or {})
    user_id = data.get("user_id") or client_data.get("user_id")
    conversation_id = data.get("conversation_id")

    if kind == "post_call_transcription":
        call_id = await service.find_call(ctx, conversation_id, user_id)
        if call_id is None:
            log.warning("webhook de una conversación desconocida: %s", conversation_id)
            return {"ok": True, "outcome": "unknown"}
        outcome = await service.handle_result(ctx, call_id, parse_conversation(data), now)
        return {"ok": True, "outcome": outcome}

    if kind == "call_initiation_failure":
        reason = str(data.get("failure_reason") or "unknown")
        outcome = await service.handle_failure_event(
            ctx, str(conversation_id or ""), user_id, reason, now
        )
        return {"ok": True, "outcome": outcome}

    # post_call_audio y tipos futuros: se aceptan sin acción (el audio se guardará cifrado en E8).
    return {"ok": True, "outcome": "ignored"}
