"""Qué debe capturar la llamada: esquema de extracción de la etapa 1 (doc 03 §7.2; doc 01 §13).

Una sola definición sirve a los dos lados:

- ``data_collection_items()`` genera los campos que ElevenLabs extrae al terminar cada llamada;
- ``parse_analysis()`` valida lo que devuelve y lo convierte en una ficha por visita.

ElevenLabs solo admite campos simples (texto, entero, booleano) y un máximo de 25 por agente.
Por eso la **primera** visita usa un campo por dato (``v1_interest_level``…) y las visitas
adicionales de una misma llamada (institución con varios médicos, hasta 5) viajan juntas en un
solo campo de texto JSON (``extra_visits_json``). Si ese JSON viene dañado, esas fichas quedan
«por completar» y nunca se pierde la primera (regla: un campo inválido no tumba la ficha).

Los nombres van en inglés, como en el resto del código y en el doc 03; las etiquetas en español
se resuelven en la interfaz.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

MAX_VISITS_PER_CALL = 5

VISIT_OUTCOMES = (
    "order_taken",  # el médico compró / encargó producto
    "commitment",  # se comprometió a recetar, probar o usar
    "sample_requested",
    "info_requested",
    "follow_up_set",  # quedó una cita o acción de seguimiento concreta
    "neutral",
    "rejected",
    "not_attended",  # la visita no se hizo o no lo atendieron
    "unknown",
)
NO_ORDER_REASONS = (
    "competitor_better",  # la competencia está mejor posicionada / le funciona mejor
    "no_need_to_switch",  # no tiene necesidad de cambiar lo que ya usa
    "price",
    "availability",  # no lo encuentra, desabastecimiento, formulario
    "needs_more_information",
    "no_time",
    "other",
    "not_applicable",  # sí hubo pedido
    "unknown",
)
RECEPTIVENESS = ("high", "medium", "low", "unknown")

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: Literal["string", "integer", "boolean"]
    description: str
    enum: tuple[str, ...] | None = None


VISIT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "interest_level",
        "integer",
        "Interés del médico en el producto según lo que cuenta el visitador, de 1 (ninguno) a 5 "
        "(muy alto). Usa 0 si el visitador no lo dijo ni se puede deducir.",
    ),
    FieldSpec(
        "visit_outcome",
        "string",
        "Resultado principal de la visita según el visitador: order_taken (el médico compró o "
        "encargó producto), commitment (se comprometió a recetar, probar o usar), "
        "sample_requested (pidió muestras), info_requested (pidió información), follow_up_set "
        "(quedó una cita o acción de seguimiento concreta), neutral (escuchó sin compromiso), "
        "rejected (rechazó), not_attended (la visita no se hizo o no lo atendieron), unknown "
        "(no se pudo determinar). Elige el más fuerte si hay varios.",
        VISIT_OUTCOMES,
    ),
    FieldSpec(
        "order_taken",
        "boolean",
        "true SOLO si el visitador dijo expresamente que el médico compró, encargó o pidió "
        "producto en esta visita. false en cualquier otro caso.",
    ),
    FieldSpec(
        "no_order_reason",
        "string",
        "Si NO hubo pedido, la razón principal que dio el visitador: competitor_better (la "
        "competencia está mejor o le funciona mejor), no_need_to_switch (no tiene necesidad de "
        "cambiar lo que ya usa), price, availability, needs_more_information, no_time, other, "
        "unknown (no lo explicó). not_applicable si sí hubo pedido.",
        NO_ORDER_REASONS,
    ),
    FieldSpec(
        "receptiveness",
        "string",
        "Disposición general del médico durante la visita: high, medium, low o unknown.",
        RECEPTIVENESS,
    ),
    FieldSpec(
        "objection",
        "string",
        "La objeción o duda principal del médico, en una frase corta con las palabras del "
        "visitador (máximo 140 caracteres). Vacío si dijo que no hubo ninguna o no se mencionó.",
    ),
    FieldSpec(
        "competitor",
        "string",
        "Marca o molécula de la competencia mencionada (por ejemplo pantoprazol, omeprazol). "
        "Vacío si no se mencionó.",
    ),
    FieldSpec(
        "current_preference",
        "string",
        "Qué formula o usa hoy el médico para este caso, si se dijo. Vacío si no se mencionó.",
    ),
    FieldSpec(
        "commitment",
        "string",
        "A qué se comprometió el médico, en una frase corta (máximo 140 caracteres). Vacío si a "
        "nada.",
    ),
    FieldSpec(
        "next_action",
        "string",
        "Qué hará el visitador después con este médico, en una frase corta (máximo 140 "
        "caracteres). Vacío si no se dijo.",
    ),
    FieldSpec(
        "next_action_in_days",
        "integer",
        "En cuántos días desde hoy quedó la próxima acción (por ejemplo 'mañana' = 1, 'en dos "
        "semanas' = 14, 'el mes entrante' = 30). 0 si no se dijo una fecha o plazo.",
    ),
    FieldSpec(
        "samples_delivered",
        "boolean",
        "true si el visitador dijo que entregó muestras en esta visita; false en otro caso.",
    ),
    FieldSpec(
        "products_discussed",
        "string",
        "Productos o líneas de las que hablaron en esta visita, separados por coma. Vacío si no "
        "se dijo.",
    ),
    FieldSpec(
        "territory_signal",
        "string",
        "Algo que el visitador notó del territorio que sirva a la gerencia (farmacias, precios, "
        "desabastecimiento, movimientos de la competencia), máximo 200 caracteres. Vacío si no "
        "dijo nada.",
    ),
    FieldSpec(
        "summary",
        "string",
        "Resumen de la visita en 1 o 2 frases (máximo 280 caracteres), en tercera persona, con lo "
        "esencial: interés, resultado, motivo si no hubo pedido y próxima acción. Sin nombres de "
        "pacientes.",
    ),
)
FIELD_BY_NAME = {f.name: f for f in VISIT_FIELDS}

GLOBAL_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "extra_visits_json",
        "string",
        "Solo si en la llamada se reportaron VARIAS visitas: un arreglo JSON con un objeto por "
        "cada visita adicional (V2, V3…), cada uno con la clave 'ref' ('V2', 'V3'…) y las mismas "
        "claves que la primera visita (interest_level, visit_outcome, order_taken, "
        "no_order_reason, receptiveness, objection, competitor, current_preference, commitment, "
        "next_action, next_action_in_days, samples_delivered, products_discussed, "
        "territory_signal, summary), con los mismos valores permitidos. Si solo hubo una visita, "
        "escribe exactamente [].",
    ),
    FieldSpec(
        "uncertain_fields",
        "string",
        "Lista separada por comas de los campos (con el prefijo de su visita, por ejemplo "
        "v1_interest_level) que el visitador no respondió, contestó de forma vaga o que tuviste "
        "que suponer. Vacío si todo quedó claro.",
    ),
    FieldSpec(
        "callback_in_minutes",
        "integer",
        "Si el visitador dijo que no puede hablar ahora y pidió que lo llamen más tarde, en "
        "cuántos minutos (por ejemplo 'en media hora' = 30, 'en una hora' = 60). 0 si no "
        "pidió que lo llamen de nuevo.",
    ),
    FieldSpec(
        "interview_complete",
        "boolean",
        "true si el visitador contó, para todas las visitas, al menos el interés y el resultado "
        "(si hubo pedido o no). false si se cortó la llamada o no pudo hablar.",
    ),
)


def data_collection_items() -> dict[str, dict[str, Any]]:
    """Campos que ElevenLabs extrae al terminar (``platform_settings.data_collection``)."""
    items: dict[str, dict[str, Any]] = {}
    for spec in VISIT_FIELDS:
        items[f"v1_{spec.name}"] = _item(spec)
    for spec in GLOBAL_FIELDS:
        items[spec.name] = _item(spec)
    return items


def _item(spec: FieldSpec) -> dict[str, Any]:
    item: dict[str, Any] = {"type": spec.type, "description": spec.description}
    if spec.enum:
        item["enum"] = list(spec.enum)
    return item


# --------------------------------------------------------------------------- lectura


@dataclass
class FieldValue:
    value: Any
    confidence: Confidence
    source: str = "call"  # call | rep_edit


@dataclass
class ParsedVisit:
    position: int  # 1 = primera visita de la llamada
    fields: dict[str, FieldValue]
    complete: bool  # tiene lo esencial (interés y resultado)
    problems: list[str]  # campos descartados por inválidos


def _raw_value(entry: Any) -> Any:
    """ElevenLabs entrega ``{"value": ..., "rationale": ...}``; en pruebas basta el valor suelto."""
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


def _clean_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or text.lower() in {"null", "none", "n/a", "ninguno", "ninguna", "-"}:
        return None
    return text[:limit]


_TEXT_LIMITS = {
    "objection": 140,
    "competitor": 80,
    "current_preference": 120,
    "commitment": 140,
    "next_action": 140,
    "products_discussed": 160,
    "territory_signal": 200,
    "summary": 280,
}


def _coerce(spec: FieldSpec, raw: Any) -> Any:
    """Devuelve el valor limpio o lanza ``ValueError`` si es inválido."""
    if raw is None:
        return None
    if spec.type == "integer":
        if isinstance(raw, bool):
            raise ValueError("entero esperado")
        try:
            number = int(float(str(raw).strip()))
        except (TypeError, ValueError):
            raise ValueError("entero esperado") from None
        if spec.name == "interest_level":
            if number == 0:
                return None  # 0 = no determinado
            if not 1 <= number <= 5:
                raise ValueError("interés fuera de 1–5")
        if spec.name == "next_action_in_days":
            if number == 0:
                return None
            if not 1 <= number <= 730:
                raise ValueError("plazo fuera de rango")
        return number
    if spec.type == "boolean":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in {"true", "sí", "si", "1", "yes"}:
            return True
        if text in {"false", "no", "0", ""}:
            return False
        raise ValueError("booleano esperado")
    cleaned = _clean_text(raw, _TEXT_LIMITS.get(spec.name, 280))
    if spec.enum:
        if cleaned is None:
            return None
        normal = cleaned.strip().lower().replace(" ", "_")
        if normal not in spec.enum:
            raise ValueError(f"valor fuera del vocabulario: {cleaned[:30]}")
        return normal
    return cleaned


def coerce_value(field: str, raw: Any) -> Any:
    """Valida el valor que el visitador escribe para un campo de la ficha.

    Devuelve el valor limpio (``None`` si borró el campo) o lanza ``ValueError``.
    """
    spec = FIELD_BY_NAME.get(field)
    if spec is None:
        raise ValueError("campo desconocido")
    if isinstance(raw, str) and not raw.strip():
        return None
    return _coerce(spec, raw)


def _uncertain(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {part.strip().lower() for part in re.split(r"[,;\n]", raw) if part.strip()}


def _visit_from_mapping(
    position: int, get: Any, prefix: str, uncertain: set[str]
) -> ParsedVisit:
    """``get(name)`` devuelve el valor crudo del campo ``name`` de esta visita."""
    fields: dict[str, FieldValue] = {}
    problems: list[str] = []
    for spec in VISIT_FIELDS:
        try:
            value = _coerce(spec, get(spec.name))
        except ValueError:
            problems.append(spec.name)
            continue
        if value is None:
            continue
        # Un booleano en false o un motivo 'unknown' no es un dato: es la ausencia de uno.
        if spec.type == "boolean" and value is False:
            doubtful = f"{prefix}{spec.name}" in uncertain
            fields[spec.name] = FieldValue(False, "low" if doubtful else "medium")
            continue
        if isinstance(value, str) and value == "unknown":
            continue
        confidence: Confidence = "low" if f"{prefix}{spec.name}" in uncertain else "high"
        fields[spec.name] = FieldValue(value, confidence)
    complete = "interest_level" in fields and (
        fields.get("visit_outcome") is not None or "order_taken" in fields
    )
    return ParsedVisit(position=position, fields=fields, complete=complete, problems=problems)


def parse_analysis(results: dict[str, Any], visit_count: int) -> list[ParsedVisit]:
    """Convierte ``analysis.data_collection_results`` en una ficha por visita (posición 1…N).

    Nunca lanza: una visita sin datos válidos devuelve una ficha vacía (``complete=False``).
    """
    uncertain = _uncertain(_clean_text(_raw_value(results.get("uncertain_fields")), 800))
    first = _visit_from_mapping(
        1, lambda name: _raw_value(results.get(f"v1_{name}")), "v1_", uncertain
    )
    visits = [first]

    extras: dict[str, dict[str, Any]] = {}
    raw_json = _raw_value(results.get("extra_visits_json"))
    if visit_count > 1 and raw_json:
        try:
            parsed = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and re.fullmatch(r"V[2-5]", str(item.get("ref", ""))):
                        extras[str(item["ref"])] = item
        except (ValueError, TypeError):
            extras = {}

    for position in range(2, visit_count + 1):
        ref = f"V{position}"
        item = extras.get(ref)
        if item is None:
            visits.append(ParsedVisit(position, {}, False, ["missing"]))
            continue
        visits.append(
            _visit_from_mapping(
                position, lambda name, item=item: item.get(name), f"v{position}_", uncertain
            )
        )
    return visits[: max(visit_count, 1)]


def callback_minutes(results: dict[str, Any]) -> int | None:
    """Minutos que pidió el visitador para que lo vuelvan a llamar (entre 5 y 240), o ``None``."""
    raw = _raw_value(results.get("callback_in_minutes"))
    try:
        minutes = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None
    return max(5, min(minutes, 240)) if minutes > 0 else None


def interview_complete(results: dict[str, Any]) -> bool:
    value = _raw_value(results.get("interview_complete"))
    return value is True or str(value).strip().lower() == "true"
