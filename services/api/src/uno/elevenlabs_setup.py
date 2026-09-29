"""Herramientas de administración del agente de voz en ElevenLabs.

Todo lo que define al agente vive en el repositorio (``infra/elevenlabs``): el guion, la voz, los
turnos y los campos a extraer. Este módulo lo aplica por API, de modo que cambiar el agente es un
cambio de código revisado y no un clic en el panel (doc 02 T5.1 ST5).

La cuenta de ElevenLabs puede ser compartida con otras campañas, así que:

- solo se crea o se actualiza el agente con el nombre de ``agent.json``; nunca se toca otro agente;
- un número que ya tiene otro agente asignado **no se reasigna** salvo orden explícita.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from uno.modules.calls.schema import data_collection_items

DEFAULT_BASE_URL = "https://api.elevenlabs.io"
REPO_ROOT = Path(__file__).resolve().parents[4]  # …/uno-visitas
DEFAULT_CONFIG_DIR = REPO_ROOT / "infra" / "elevenlabs"

END_CALL_DESCRIPTION = (
    "Cuelga la llamada. Úsala solo cuando ya tengas lo esencial de todas las visitas, ya hayas "
    "dicho el resumen y te hayas despedido, o cuando el visitador no pueda hablar. Invócala en "
    "ese turno sin decir nada más."
)
VOICEMAIL_DESCRIPTION = (
    "Detecta que contestó un buzón de voz o una grabación en lugar de una persona. Si ocurre, "
    "termina la llamada sin mencionar detalles de las visitas."
)


class ElevenLabsError(RuntimeError):
    pass


def _strip_comments(value: Any) -> Any:
    """Quita las claves que empiezan por ``_`` (comentarios del JSON de configuración)."""
    if isinstance(value, dict):
        return {k: _strip_comments(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, list):
        return [_strip_comments(v) for v in value]
    return value


def load_config(config_dir: Path = DEFAULT_CONFIG_DIR) -> tuple[dict[str, Any], str]:
    config = _strip_comments(json.loads((config_dir / "agent.json").read_text(encoding="utf-8")))
    prompt = (config_dir / "prompt.es.md").read_text(encoding="utf-8").strip()
    return config, prompt


def _optional(config: dict[str, Any], key: str) -> dict[str, Any]:
    return {key: config[key]} if key in config else {}


def build_payload(config: dict[str, Any], prompt: str) -> dict[str, Any]:
    """Cuerpo de ``POST /v1/convai/agents/create`` (y de ``PATCH``) a partir del repositorio."""
    conversation_config: dict[str, Any] = {
        "agent": {
            "language": config["language"],
            "first_message": config["first_message"],
            "dynamic_variables": {
                "dynamic_variable_placeholders": config["dynamic_variable_placeholders"]
            },
            "prompt": {
                "prompt": prompt,
                "llm": config["llm"],
                "temperature": config["temperature"],
                "max_tokens": config["max_tokens"],
                # Solo algunos modelos admiten «reasoning effort»: modelo y esfuerzo van juntos.
                **_optional(config, "reasoning_effort"),
                "built_in_tools": {
                    "end_call": {
                        "type": "system",
                        "name": "end_call",
                        "description": END_CALL_DESCRIPTION,
                        "params": {"system_tool_type": "end_call"},
                    },
                    "voicemail_detection": {
                        "type": "system",
                        "name": "voicemail_detection",
                        "description": VOICEMAIL_DESCRIPTION,
                        "params": {"system_tool_type": "voicemail_detection"},
                    },
                },
            },
        },
        "tts": config["tts"],
        "asr": config["asr"],
        "turn": config["turn"],
        "conversation": config["conversation"],
    }
    platform_settings: dict[str, Any] = {
        "data_collection": data_collection_items(),
        "privacy": config["privacy"],
        "call_limits": config["call_limits"],
    }
    return {
        "name": config["name"],
        "tags": config.get("tags", []),
        "conversation_config": conversation_config,
        "platform_settings": platform_settings,
    }


class ElevenLabsAdmin:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        if not api_key:
            raise ElevenLabsError("Falta UNO_ELEVENLABS_API_KEY")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"xi-api-key": api_key},
            timeout=httpx.Timeout(60.0),
        )

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._http.request(method, path, **kwargs)
        if response.status_code >= 400:
            detail = response.text[:1500]
            raise ElevenLabsError(f"{method} {path} → {response.status_code}: {detail}")
        return response.json() if response.content else {}

    # ------------------------------------------------------------------ agentes

    def list_agents(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["cursor"] = cursor
            page = self._request("GET", "/v1/convai/agents", params=params)
            out.extend(page.get("agents", []))
            if not page.get("has_more"):
                return out
            cursor = page.get("next_cursor")

    def find_agent(self, name: str) -> dict[str, Any] | None:
        found = [a for a in self.list_agents() if a.get("name") == name]
        if len(found) > 1:
            raise ElevenLabsError(f"Hay {len(found)} agentes llamados «{name}»; resuélvelo a mano")
        return found[0] if found else None

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/convai/agents/{agent_id}")

    def apply(self, config_dir: Path = DEFAULT_CONFIG_DIR) -> tuple[str, bool]:
        """Crea el agente si no existe (por nombre) o lo actualiza. Devuelve ``(id, creado)``."""
        config, prompt = load_config(config_dir)
        payload = build_payload(config, prompt)
        existing = self.find_agent(config["name"])
        if existing is None:
            created = self._request("POST", "/v1/convai/agents/create", json=payload)
            return created["agent_id"], True
        agent_id = existing["agent_id"]
        body = {k: v for k, v in payload.items() if k != "name"}
        body["name"] = payload["name"]
        self._request("PATCH", f"/v1/convai/agents/{agent_id}", json=body)
        return agent_id, False

    # ------------------------------------------------------------------ números

    def list_numbers(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/convai/phone-numbers")

    def assign_number(self, phone_number_id: str, agent_id: str, *, force: bool = False) -> None:
        numbers = {n["phone_number_id"]: n for n in self.list_numbers()}
        number = numbers.get(phone_number_id)
        if number is None:
            raise ElevenLabsError(f"No existe el número {phone_number_id}")
        current = (number.get("assigned_agent") or {}).get("agent_id")
        if current and current != agent_id and not force:
            name = (number.get("assigned_agent") or {}).get("agent_name")
            raise ElevenLabsError(
                f"{number['phone_number']} ya está asignado al agente «{name}». "
                "Reasignarlo detendría esa campaña; usa --force-reassign solo si estás seguro."
            )
        self._request(
            "PATCH", f"/v1/convai/phone-numbers/{phone_number_id}", json={"agent_id": agent_id}
        )

    # ------------------------------------------------------------------ pruebas sin llamar

    def simulate(
        self,
        agent_id: str,
        *,
        persona: str,
        dynamic_variables: dict[str, Any],
        max_turns: int = 24,
    ) -> dict[str, Any]:
        """Conversación de texto entre el agente y un visitador simulado (no llama a nadie)."""
        body = {
            "simulation_specification": {
                "simulated_user_config": {
                    "language": "es",
                    "prompt": {"prompt": persona, "llm": "gemini-2.5-flash", "temperature": 0.3},
                },
                "dynamic_variables": dynamic_variables,
            },
            "new_turns_limit": max_turns,
        }
        return self._request(
            "POST", f"/v1/convai/agents/{agent_id}/simulate-conversation", json=body
        )
