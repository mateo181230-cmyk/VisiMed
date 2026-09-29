"""Proveedor de voz: quien marca la llamada y devuelve la conversación (doc 01 §12.8).

El resto del sistema solo conoce la interfaz ``VoiceProvider``. Hay dos implementaciones:

- ``ElevenLabsProvider``: la real (agente de voz de ElevenLabs sobre la troncal SIP de Telyaco).
- ``FakeProvider``: simula al proveedor con el mismo contrato, para desarrollar y probar el ciclo
  completo sin marcar a nadie ni gastar minutos.

Tanto el webhook de fin de llamada como la consulta ``GET /conversations/{id}`` devuelven la misma
estructura de conversación; ``parse_conversation`` la lee en un solo lugar.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol

import httpx

_AUDIO_TAG = re.compile(r"\[[a-zA-Z ]{2,20}\]\s*")
VOICEMAIL_TOOL = "voicemail_detection"


def clean_utterance(text: str | None) -> str:
    """Quita las etiquetas de expresión de la voz (``[happy]``) que quedan en la transcripción."""
    return _AUDIO_TAG.sub("", text or "").strip()


class ProviderError(RuntimeError):
    """Falla del proveedor al marcar o consultar. ``retryable``: tiene sentido volver a intentar."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class DialRequest:
    call_id: uuid.UUID
    to_phone: str
    dynamic_variables: dict[str, str]


@dataclass(frozen=True)
class Dialed:
    conversation_id: str | None
    provider_call_id: str | None = None


@dataclass
class Turn:
    role: Literal["agent", "user"]
    text: str
    t: float | None = None  # segundos desde el inicio de la llamada
    tools: list[str] = field(default_factory=list)


@dataclass
class ConversationResult:
    conversation_id: str
    status: Literal["pending", "done", "failed"]
    turns: list[Turn] = field(default_factory=list)
    data_collection: dict[str, Any] = field(default_factory=dict)
    summary: str | None = None
    duration_s: int | None = None
    termination_reason: str | None = None
    failure_reason: str | None = None  # busy | no-answer | unknown (webhook de fallo)

    @property
    def user_turns(self) -> int:
        # Un turno de puro silencio o ruido («…») no cuenta como que la persona habló.
        return sum(1 for turn in self.turns if turn.role == "user" and re.search(r"\w", turn.text))

    @property
    def voicemail(self) -> bool:
        return any(VOICEMAIL_TOOL in turn.tools for turn in self.turns)

    def transcript_json(self) -> list[dict[str, Any]]:
        return [
            {"role": turn.role, "text": turn.text, "t": turn.t}
            for turn in self.turns
            if turn.text.strip()
        ]


class VoiceProvider(Protocol):
    name: str

    async def place_call(self, request: DialRequest) -> Dialed: ...

    async def fetch_conversation(self, conversation_id: str) -> ConversationResult | None: ...


# --------------------------------------------------------------------------- lectura común

_PENDING = {"initiated", "in-progress", "processing", "in_progress"}


def parse_conversation(payload: dict[str, Any]) -> ConversationResult:
    """Convierte una conversación de ElevenLabs (webhook o GET) en ``ConversationResult``."""
    raw_status = str(payload.get("status") or "").lower()
    status: Literal["pending", "done", "failed"] = (
        "done" if raw_status == "done" else "failed" if raw_status == "failed" else "pending"
    )
    turns: list[Turn] = []
    for item in payload.get("transcript") or []:
        role: Literal["agent", "user"] = "agent" if item.get("role") == "agent" else "user"
        tools = [
            str(call.get("tool_name") or call.get("name") or "")
            for call in (item.get("tool_calls") or [])
        ]
        turns.append(
            Turn(
                role=role,
                text=clean_utterance(item.get("message")),
                t=item.get("time_in_call_secs"),
                tools=[t for t in tools if t],
            )
        )
    metadata = payload.get("metadata") or {}
    analysis = payload.get("analysis") or {}
    duration = metadata.get("call_duration_secs")
    return ConversationResult(
        conversation_id=str(payload.get("conversation_id") or ""),
        status=status,
        turns=turns,
        data_collection=analysis.get("data_collection_results") or {},
        summary=analysis.get("transcript_summary"),
        duration_s=int(duration) if isinstance(duration, int | float) else None,
        termination_reason=metadata.get("termination_reason"),
    )


# --------------------------------------------------------------------------- ElevenLabs


Channel = Literal["sip_trunk", "twilio"]
_OUTBOUND_PATH: dict[str, str] = {
    "sip_trunk": "/v1/convai/sip-trunk/outbound-call",
    "twilio": "/v1/convai/twilio/outbound-call",
}


class ElevenLabsProvider:
    """Llama con un agente de ElevenLabs por un número de la cuenta (troncal SIP o Twilio).

    El canal se detecta solo la primera vez, mirando de qué tipo es el número; el cuerpo de la
    petición es el mismo, cambia el endpoint. Si se da ``channel`` no se consulta nada.
    """

    name = "elevenlabs"

    def __init__(
        self,
        *,
        api_key: str,
        agent_id: str,
        phone_number_id: str,
        base_url: str = "https://api.elevenlabs.io",
        channel: Channel | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._phone_number_id = phone_number_id
        self._channel: Channel | None = channel
        self._http = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"xi-api-key": api_key},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def _resolve_channel(self) -> Channel:
        if self._channel is not None:
            return self._channel
        try:
            response = await self._http.get(f"/v1/convai/phone-numbers/{self._phone_number_id}")
        except httpx.HTTPError as exc:
            raise ProviderError(f"sin respuesta del proveedor: {type(exc).__name__}") from exc
        if response.status_code == 404:
            raise ProviderError("el número configurado no existe en ElevenLabs", retryable=False)
        if response.status_code >= 400:
            raise ProviderError(f"no se pudo leer el número ({response.status_code})")
        self._channel = "twilio" if response.json().get("provider") == "twilio" else "sip_trunk"
        return self._channel

    async def place_call(self, request: DialRequest) -> Dialed:
        channel = await self._resolve_channel()
        body = {
            "agent_id": self._agent_id,
            "agent_phone_number_id": self._phone_number_id,
            "to_number": request.to_phone,
            "conversation_initiation_client_data": {
                "dynamic_variables": request.dynamic_variables,
                "user_id": str(request.call_id),  # vuelve en el webhook: doble llave de cruce
            },
        }
        try:
            response = await self._http.post(_OUTBOUND_PATH[channel], json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"sin respuesta del proveedor: {type(exc).__name__}") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise ProviderError(f"proveedor no disponible ({response.status_code})")
        if response.status_code >= 400:
            # Configuración o número inválidos: reintentar no lo arregla.
            raise ProviderError(
                f"el proveedor rechazó la llamada ({response.status_code}): {response.text[:200]}",
                retryable=False,
            )
        data = response.json()
        if not data.get("success", True):
            raise ProviderError(str(data.get("message") or "llamada rechazada")[:200])
        return Dialed(data.get("conversation_id"), data.get("sip_call_id") or data.get("callSid"))

    async def fetch_conversation(self, conversation_id: str) -> ConversationResult | None:
        try:
            response = await self._http.get(f"/v1/convai/conversations/{conversation_id}")
        except httpx.HTTPError as exc:
            raise ProviderError(f"sin respuesta del proveedor: {type(exc).__name__}") from exc
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise ProviderError(f"consulta rechazada ({response.status_code})")
        return parse_conversation(response.json())

    async def aclose(self) -> None:
        await self._http.aclose()


# --------------------------------------------------------------------------- simulado


ScriptFn = Callable[[DialRequest], "FakeOutcome"]


@dataclass
class FakeOutcome:
    """Qué ocurre con una llamada simulada."""

    kind: Literal["answered", "no_answer", "busy", "voicemail", "error"] = "answered"
    delay: timedelta = timedelta(seconds=0)
    data_collection: dict[str, Any] = field(default_factory=dict)
    turns: list[Turn] = field(default_factory=list)
    duration_s: int = 75


def canned_data(visit_count: int = 1) -> dict[str, Any]:
    """Resultado de ejemplo (el del escenario «sin pedido, no necesita cambiar»)."""
    first = {
        "v1_interest_level": {"value": 4},
        "v1_visit_outcome": {"value": "follow_up_set"},
        "v1_order_taken": {"value": False},
        "v1_no_order_reason": {"value": "no_need_to_switch"},
        "v1_receptiveness": {"value": "high"},
        "v1_objection": {"value": ""},
        "v1_competitor": {"value": "pantoprazol"},
        "v1_current_preference": {"value": "pantoprazol"},
        "v1_commitment": {"value": ""},
        "v1_next_action": {"value": "Llevarle muestras"},
        "v1_next_action_in_days": {"value": 14},
        "v1_samples_delivered": {"value": False},
        "v1_products_discussed": {"value": "ESOMED"},
        "v1_territory_signal": {"value": ""},
        "v1_summary": {
            "value": "Interés 4/5 en ESOMED; no hubo pedido porque ya usa pantoprazol y le "
            "funciona. Quedó en probarlo si le llevan muestras en dos semanas."
        },
        "uncertain_fields": {"value": ""},
        "interview_complete": {"value": True},
        "extra_visits_json": {"value": "[]"},
    }
    if visit_count > 1:
        import json

        extras = [
            {
                "ref": f"V{n}",
                "interest_level": 5,
                "visit_outcome": "order_taken",
                "order_taken": True,
                "no_order_reason": "not_applicable",
                "receptiveness": "high",
                "next_action": "Volver en un mes",
                "next_action_in_days": 30,
                "summary": "Hizo un pedido de 10 cajas de ESOMED.",
            }
            for n in range(2, visit_count + 1)
        ]
        first["extra_visits_json"] = {"value": json.dumps(extras, ensure_ascii=False)}
    return first


class FakeProvider:
    """Proveedor simulado. ``script`` decide qué pasa con cada llamada (por defecto contesta)."""

    name = "fake"

    def __init__(
        self,
        script: ScriptFn | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        from uno import clock

        self._script = script or (lambda req: FakeOutcome())
        self._now = now or clock.now
        self.requests: list[DialRequest] = []
        self._calls: dict[str, tuple[datetime, FakeOutcome, DialRequest]] = {}
        self.fail_next_dial: ProviderError | None = None

    async def place_call(self, request: DialRequest) -> Dialed:
        if self.fail_next_dial is not None:
            error, self.fail_next_dial = self.fail_next_dial, None
            raise error
        self.requests.append(request)
        conversation_id = f"fake_conv_{uuid.uuid4().hex[:12]}"
        self._calls[conversation_id] = (self._now(), self._script(request), request)
        return Dialed(conversation_id, f"fake_sip_{uuid.uuid4().hex[:8]}")

    async def fetch_conversation(self, conversation_id: str) -> ConversationResult | None:
        entry = self._calls.get(conversation_id)
        if entry is None:
            return None
        started, outcome, request = entry
        if self._now() < started + outcome.delay:
            return ConversationResult(conversation_id, "pending")
        if outcome.kind == "error":
            return ConversationResult(conversation_id, "failed", termination_reason="error")
        if outcome.kind in ("no_answer", "busy"):
            return ConversationResult(
                conversation_id,
                "failed",
                failure_reason="no-answer" if outcome.kind == "no_answer" else "busy",
            )
        if outcome.kind == "voicemail":
            turns = [Turn("agent", "Hola…", 0.0), Turn("agent", "", 4.0, [VOICEMAIL_TOOL])]
            return ConversationResult(
                conversation_id, "done", turns=turns, duration_s=6, termination_reason="voicemail"
            )
        visit_count = int(request.dynamic_variables.get("num_visitas", "1"))
        turns = outcome.turns or [
            Turn("agent", "Hola, soy UNO. Esta llamada se graba para armar tu reporte.", 0.0),
            Turn("user", "Hola, me fue bien.", 5.0),
            Turn("agent", "Listo. Te dejo el resumen en la app para que lo confirmes.", 60.0),
        ]
        return ConversationResult(
            conversation_id,
            "done",
            turns=turns,
            data_collection=outcome.data_collection or canned_data(visit_count),
            summary="Resumen simulado de la llamada.",
            duration_s=outcome.duration_s,
            termination_reason="agent_ended",
        )
