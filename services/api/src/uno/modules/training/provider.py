"""Proveedor de la conversación con el médico virtual (doc 04 §5.2, principio 2).

El resto del módulo solo conoce ``ConversationProvider``:

- ``TavusProvider``: el real. Crea la conversación (el celular se une por WebRTC), la termina, trae
  la transcripción y publica o borra los médicos virtuales (PAL). La cuenta de Tavus es compartida:
  solo toca PAL cuyo nombre empieza por ``PAL_PREFIX``.
- ``FakeProvider``: simula el ciclo con una transcripción de ejemplo, para desarrollar y probar sin
  gastar minutos. Su URL empieza por ``fake:`` y la app la reconoce como «modo de prueba».

``UNO_TRAINING_BACKEND=off`` (por defecto) no crea ningún proveedor: el médico no está disponible.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

PAL_PREFIX = "UNO Entrenar"


class ProviderError(RuntimeError):
    """Falla del proveedor. ``code`` es estable: la app decide el mensaje con él."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ConversationRequest:
    pal_id: str | None
    name: str
    context: str
    greeting: str
    callback_url: str | None
    max_seconds: int
    audio_only: bool
    scenario_slug: str


@dataclass(frozen=True)
class Created:
    conversation_id: str
    conversation_url: str


@dataclass
class TranscriptTurn:
    role: Literal["rep", "doctor"]
    text: str
    t: float | None = None
    duration: float | None = None


@dataclass
class Transcript:
    ready: bool
    turns: list[TranscriptTurn] = field(default_factory=list)
    ended: bool = False
    end_reason: str | None = None


class ConversationProvider(Protocol):
    name: str

    async def create_conversation(self, request: ConversationRequest) -> Created: ...

    async def end_conversation(self, conversation_id: str) -> None: ...

    async def fetch_transcript(self, conversation_id: str) -> Transcript: ...

    async def probe(self, pal_id: str | None = None) -> str | None: ...


# --------------------------------------------------------------------------- lectura común


def parse_transcript(raw: list[dict[str, Any]] | None) -> list[TranscriptTurn]:
    """Turnos de Tavus (``role`` user/assistant) → turnos de la práctica (rep/doctor)."""
    turns: list[TranscriptTurn] = []
    for item in raw or []:
        role = str(item.get("role") or "")
        if role not in ("user", "assistant", "replica", "pal"):
            continue  # «system» y otros no son parte de la conversación
        content = str(item.get("content") or item.get("text") or "").strip()
        if not content:
            continue
        mapped: Literal["rep", "doctor"] = "rep" if role == "user" else "doctor"
        seconds = item.get("seconds_from_start")
        duration = item.get("duration")
        turns.append(
            TranscriptTurn(
                mapped,
                content,
                float(seconds) if isinstance(seconds, int | float) else None,
                float(duration) if isinstance(duration, int | float) else None,
            )
        )
    return turns


def transcript_from_conversation(payload: dict[str, Any]) -> Transcript:
    """Lee ``GET /v2/conversations/{id}?verbose=true`` (eventos de la conversación)."""
    events = payload.get("events") or []
    ended = str(payload.get("status") or "") == "ended"
    reason = None
    raw = None
    for event in events:
        kind = event.get("event_type") or event.get("message_type")
        props = event.get("properties") or {}
        if kind in ("application.transcription_ready", "application.transcript_ready"):
            raw = props.get("transcript")
        elif kind == "system.shutdown":
            ended = True
            reason = props.get("shutdown_reason")
    if raw is None and isinstance(payload.get("transcript"), list):
        raw = payload["transcript"]
    if raw is None:
        return Transcript(ready=False, ended=ended, end_reason=reason)
    return Transcript(ready=True, turns=parse_transcript(raw), ended=True, end_reason=reason)


# --------------------------------------------------------------------------- Tavus


def _error_for(status: int, body: str) -> ProviderError:
    if status == 402:
        return ProviderError("no_credits", "La cuenta de Tavus no tiene créditos de conversación")
    if status in (401, 403):
        return ProviderError("auth", f"Tavus rechazó la llave ({status})")
    if status == 429:
        return ProviderError(
            "busy", "Tavus está ocupado (límite de conversaciones)", retryable=True
        )
    if status >= 500:
        return ProviderError("unavailable", f"Tavus no disponible ({status})", retryable=True)
    return ProviderError("rejected", f"Tavus rechazó la solicitud ({status}): {body[:200]}")


class TavusProvider:
    name = "tavus"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://tavusapi.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._http = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"x-api-key": api_key},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(
                "unavailable", f"sin respuesta de Tavus: {type(exc).__name__}", retryable=True
            ) from exc

    async def create_conversation(self, request: ConversationRequest) -> Created:
        if not request.pal_id:
            raise ProviderError("not_published", "El escenario no tiene médico publicado en Tavus")
        body: dict[str, Any] = {
            "pal_id": request.pal_id,
            "conversation_name": request.name,
            "conversational_context": request.context,
            "custom_greeting": request.greeting,
            "audio_only": request.audio_only,
            "properties": {
                "max_call_duration": request.max_seconds,
                "participant_left_timeout": 10,
                "participant_absent_timeout": 90,
                "languages": ["es"],
            },
        }
        if request.callback_url:
            body["callback_url"] = request.callback_url
        response = await self._request("POST", "/v2/conversations", json=body)
        if response.status_code >= 400:
            raise _error_for(response.status_code, response.text)
        data = response.json()
        return Created(str(data["conversation_id"]), str(data["conversation_url"]))

    async def end_conversation(self, conversation_id: str) -> None:
        response = await self._request("POST", f"/v2/conversations/{conversation_id}/end")
        if response.status_code >= 400 and response.status_code not in (400, 404):
            raise _error_for(response.status_code, response.text)

    async def fetch_transcript(self, conversation_id: str) -> Transcript:
        response = await self._request(
            "GET", f"/v2/conversations/{conversation_id}", params={"verbose": "true"}
        )
        if response.status_code == 404:
            return Transcript(ready=False, ended=True, end_reason="not_found")
        if response.status_code >= 400:
            raise _error_for(response.status_code, response.text)
        return transcript_from_conversation(response.json())

    # ----------------------------------------------------------- administración (CLI)

    async def list_pals(self) -> list[dict[str, Any]]:
        """Todos los PAL de la cuenta, de a 100 por página (corta si una página no trae nuevos)."""
        pals: dict[str, dict[str, Any]] = {}
        for page in range(1, 21):
            response = await self._request("GET", "/v2/pals", params={"limit": 100, "page": page})
            if response.status_code >= 400:
                raise _error_for(response.status_code, response.text)
            data = response.json()
            batch = list(data.get("data") or [])
            fresh = {str(p.get("pal_id")): p for p in batch if str(p.get("pal_id")) not in pals}
            pals.update(fresh)
            total = data.get("total_count")
            if not fresh or len(batch) < 100 or (isinstance(total, int) and len(pals) >= total):
                break
        return list(pals.values())

    async def create_pal(self, payload: dict[str, Any]) -> str:
        if not str(payload.get("pal_name", "")).startswith(PAL_PREFIX):
            raise ProviderError("rejected", "Solo se crean PAL con el prefijo del módulo")
        response = await self._request("POST", "/v2/pals", json=payload)
        if response.status_code >= 400:
            raise _error_for(response.status_code, response.text)
        return str(response.json()["pal_id"])

    async def delete_pal(self, pal_id: str, *, expected_prefix: str = PAL_PREFIX) -> bool:
        """Borra un PAL propio. Se niega si el nombre no empieza por el prefijo del módulo."""
        response = await self._request("GET", f"/v2/pals/{pal_id}")
        if response.status_code in (400, 404):
            return False
        if response.status_code >= 400:
            raise _error_for(response.status_code, response.text)
        data = response.json()
        data = (data.get("data") or [data])[0] if isinstance(data.get("data"), list) else data
        if not str(data.get("pal_name") or "").startswith(expected_prefix):
            raise ProviderError("rejected", f"El PAL {pal_id} no es de este módulo; no se borra")
        deleted = await self._request("DELETE", f"/v2/pals/{pal_id}")
        return deleted.status_code in (200, 204)

    async def probe(self, pal_id: str | None = None) -> str | None:
        """Crea una conversación en ``test_mode`` (sin costo): ¿Tavus aceptaría una real?

        Devuelve ``None`` si la cuenta puede crear conversaciones, o el código del problema. La
        conversación de prueba se borra enseguida para no ensuciar la cuenta compartida.
        """
        if pal_id is None:
            pals = await self.list_pals()
            own = [p for p in pals if str(p.get("pal_name")).startswith(PAL_PREFIX)]
            if not own:
                return "not_published"
            pal_id = str(own[0]["pal_id"])
        response = await self._request(
            "POST",
            "/v2/conversations",
            json={"pal_id": pal_id, "test_mode": True, "conversation_name": "UNO prueba"},
        )
        if response.status_code >= 400:
            return _error_for(response.status_code, response.text).code
        conversation_id = str(response.json().get("conversation_id") or "")
        if conversation_id:
            # Si no se pudo borrar, Tavus la cierra sola: nunca tuvo réplica.
            with contextlib.suppress(ProviderError):
                await self._request("DELETE", f"/v2/conversations/{conversation_id}")
        return None

    async def aclose(self) -> None:
        await self._http.aclose()


# --------------------------------------------------------------------------- simulado

TranscriptFn = Callable[[ConversationRequest], list[TranscriptTurn]]


def _sample_transcript(request: ConversationRequest) -> list[TranscriptTurn]:
    """Una visita bien hecha (el caso aprobado del prototipo para ese escenario)."""
    from uno.modules.training.samples import SAMPLE_VISITS

    turns = SAMPLE_VISITS.get(request.scenario_slug) or next(iter(SAMPLE_VISITS.values()))
    return [TranscriptTurn(role, text, float(i * 12), 10.0) for i, (role, text) in enumerate(turns)]


class FakeProvider:
    """Simulado: ``create`` devuelve una URL ``fake:`` y la transcripción está lista al terminar."""

    name = "fake"

    def __init__(self, transcript: TranscriptFn | None = None) -> None:
        self._transcript = transcript or _sample_transcript
        self.requests: list[ConversationRequest] = []
        self.ended: list[str] = []
        self.fail_next: ProviderError | None = None
        self.transcript_ready = True
        self.probe_result: str | None = None
        self.probes = 0
        self._by_id: dict[str, ConversationRequest] = {}

    async def create_conversation(self, request: ConversationRequest) -> Created:
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error
        self.requests.append(request)
        conversation_id = f"fake_{uuid.uuid4().hex[:12]}"
        self._by_id[conversation_id] = request
        return Created(conversation_id, f"fake:{conversation_id}")

    async def end_conversation(self, conversation_id: str) -> None:
        self.ended.append(conversation_id)

    async def fetch_transcript(self, conversation_id: str) -> Transcript:
        request = self._by_id.get(conversation_id)
        if request is None:
            return Transcript(ready=False, ended=True, end_reason="not_found")
        if conversation_id not in self.ended or not self.transcript_ready:
            return Transcript(ready=False)
        return Transcript(ready=True, turns=self._transcript(request), ended=True)

    async def probe(self, pal_id: str | None = None) -> str | None:
        self.probes += 1
        return self.probe_result
