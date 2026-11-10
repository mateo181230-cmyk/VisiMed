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
from datetime import date
from typing import Any, Literal

from uno.modules.calls.snc_report import SNCReport, normalize_report, EXTRACTION_DESCRIPTION

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


CORE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("snc_report_json", "string", EXTRACTION_DESCRIPTION),
    FieldSpec(
        "interest_level",
        "integer",
        "Interés del médico en el producto según lo que cuenta el visitador, de 1 (ninguno) a 5 "
        "(muy alto). Solo un número explícito sobre INTERÉS, no la receptividad. "
        "Usa 0 si no lo dijo. Nunca deduzcas una puntuación de 'bien' o 'interesado'.",
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
        "true SOLO si dijo expresamente que compró o encargó producto. false si dijo que no "
        "hubo pedido. Si no se habló de pedidos, inclúyelo en uncertain_fields; no presupongas no.",
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
        "Objeciones Y preguntas del médico, con las palabras del visitador, máximo 500 "
        "caracteres. 'No hubo objeciones ni preguntas' SOLO si lo dijo; vacío si no se habló.",
    ),
    FieldSpec(
        "competitor",
        "string",
        "Marca O molécula mencionada como competencia o producto que el médico usa actualmente "
        "(por ejemplo pantoprazol, omeprazol). Conserva la molécula aunque no conozca la marca o "
        "diga que no mencionó OTRA competencia; esa negativa no borra la referencia anterior. "
        "Vacío solo si no nombró ninguna marca ni molécula.",
    ),
    FieldSpec(
        "current_preference",
        "string",
        "Qué formula o usa hoy el médico para este caso, si se dijo. Vacío si no se mencionó.",
    ),
    FieldSpec(
        "commitment",
        "string",
        "Compromisos adquiridos, identificando quién hará qué: médico y visitador. Máximo "
        "500 caracteres. 'No quedaron compromisos' si lo dijo explícitamente; "
        "vacío si no se habló.",
    ),
    FieldSpec(
        "next_action",
        "string",
        "Qué hará el visitador después con este médico, en una frase corta (máximo 300 "
        "caracteres). 'No se acordó próximo paso' si lo dijo explícitamente. Vacío si no se habló.",
    ),
    FieldSpec(
        "next_action_in_days",
        "integer",
        "En cuántos días desde hoy quedó la próxima acción (por ejemplo 'mañana' = 1, 'en dos "
        "semanas' = 14). 0 si no dijo un plazo preciso. No conviertas 'el mes entrante' en 30 "
        "ni 'pronto' en un número. Para fecha concreta utiliza next_action_date en details_json.",
    ),
    FieldSpec(
        "samples_delivered",
        "boolean",
        "true si el visitador dijo que entregó muestras en esta visita; false en otro caso.",
    ),
    FieldSpec(
        "products_discussed",
        "string",
        "Productos o líneas efectivamente presentados en esta visita, separados por coma. "
        "No copies la agenda ni incluyas competidores o categorías usadas como criterio "
        "(ejemplo: 'escoger IBP' no significa que presentó un producto llamado IBP). "
        "Vacío si no se dijo.",
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
        "Resumen fiel en tercera persona, máximo 800 caracteres: producto, objetivo, "
        "conversación, intereses/desintereses, reacción, objeciones o preguntas, información "
        "nueva, competencia, compromisos y seguimiento con fecha SOLO si se mencionaron. "
        "Incorpora las últimas correcciones. Excluye datos identificables de pacientes.",
    ),
)

# El proveedor admite 25 ítems simples. Los detalles se extraen en un único JSON y se
# validan campo por campo; conservamos los campos anteriores para reportes y agentes antiguos.
DETAIL_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "doctor_commitment",
        "string",
        "Acción a la que se comprometió explícitamente el MÉDICO, sin incluir lo que hará "
        "el visitador. Conserva cantidad y plazo si los dijo. 'No quedó compromiso del médico' "
        "solo si se afirmó; null si no se habló. Máximo 500 caracteres.",
    ),
    FieldSpec(
        "representative_commitment",
        "string",
        "Nueva acción o entrega que quedó a cargo del VISITADOR para después de esta visita. "
        "No confundas el objetivo comercial, el compromiso del médico ni una entrega ya "
        "realizada. null si no se mencionó; máximo 500 caracteres.",
    ),
    FieldSpec(
        "previous_commitment_fulfilled",
        "string",
        "Cumplimiento del pendiente del VISITADOR de la visita anterior, según confirmación "
        "explícita en el relato: yes (lo cumplió), partial (cumplió una parte), "
        "no (no lo cumplió), "
        "unknown (no se confirmó). Entregar un documento no prueba que logró el objetivo actual.",
        ("yes", "partial", "no", "unknown"),
    ),
    FieldSpec(
        "objective_progress",
        "string",
        "Avance del objetivo comercial según evidencia explícita del relato: achieved si "
        "se cumplió el objetivo acordado, partial si se obtuvo solo parte, not_achieved si "
        "dijo que no avanzó, unknown sin evidencia suficiente. No deduzcas avance del interés, "
        "de la receptividad ni de haber entregado el material pendiente.",
        ("achieved", "partial", "not_achieved", "unknown"),
    ),
    FieldSpec(
        "commitment_quantity",
        "integer",
        "Cantidad positiva de pacientes o unidades a la que el MÉDICO se comprometió "
        "explícitamente. null si dijo 'algunos', 'lo consideraré', no dio cantidad o la cifra "
        "solo figuraba en el objetivo de la agenda. Nunca deduzcas ni propongas un número.",
    ),
    FieldSpec(
        "commitment_due_date",
        "string",
        "Fecha concreta del compromiso del MÉDICO en YYYY-MM-DD, solo si quedó explícitamente "
        "acordada. null para plazos vagos como 'las próximas semanas'; no inventes una fecha.",
    ),
    FieldSpec(
        "next_visit_objective",
        "string",
        "Objetivo comercial acordado explícitamente para la siguiente visita, máximo 300 "
        "caracteres. Distingue el avance esperado del médico de entregas pendientes del visitador. "
        "null si no lo acordaron; nunca lo redactes como recomendación propia.",
    ),
    FieldSpec(
        "location_change_reason",
        "string",
        "Motivo del cambio de ubicación contado por el VISITADOR, máximo 500 caracteres. "
        "null si no lo explicó. No deduzcas fraude, falta de visita ni que lo pidió el médico "
        "a partir de la ubicación; conserva únicamente su explicación.",
    ),
    FieldSpec(
        "visit_objective",
        "string",
        "Objetivo de la visita según el visitador, máximo 300 caracteres. 'Presenté X para Y' "
        "expresa el objetivo Y (por ejemplo conocer necesidades de material). Recoge el "
        "propósito del relato inicial; una respuesta vaga a una pregunta repetida no lo borra "
        "sin una corrección explícita.",
    ),
    FieldSpec(
        "discussion",
        "string",
        "Qué se habló con el médico, máximo 1000 caracteres, "
        "sin datos identificables de pacientes.",
    ),
    FieldSpec(
        "doctor_interest",
        "string",
        "Qué temas o productos le interesaron al médico, máximo 500 caracteres.",
    ),
    FieldSpec(
        "doctor_disinterest",
        "string",
        "Qué no le interesó o no quiso abordar/cambiar; máximo 500 caracteres. "
        "'No manifestó desinterés' SOLO ante una negativa explícita del visitador. "
        "Si no se preguntó ni lo mencionó, null; no conviertas silencio en una negativa.",
    ),
    FieldSpec(
        "doctor_reaction",
        "string",
        "Percepción o reacción observada, según el visitador, máximo 500 caracteres. "
        "No diagnostiques personalidad.",
    ),
    FieldSpec(
        "new_information",
        "string",
        "Información nueva que entregó el médico, máximo 700 caracteres. "
        "'No entregó información nueva' SOLO ante una negativa explícita del visitador. "
        "Si no se preguntó ni se mencionó, null; nunca supongas que no hubo novedades.",
    ),
    FieldSpec(
        "receptiveness_score",
        "integer",
        "Receptividad de 1 a 5 explícitamente indicada por el visitador. "
        "0 si no la indicó; no inferir ni confundir con interés.",
    ),
    FieldSpec(
        "free_note",
        "string",
        "Nota libre de una situación importante, máximo 700 caracteres. Incluye indicaciones "
        "de coordinación (por ejemplo atender o coordinar los miércoles), aunque las contó "
        "antes de la pregunta final. 'Nada adicional' si lo dijo explícitamente y no mencionó "
        "otra situación relevante; null si no se habló de notas ni hubo situación relevante.",
    ),
    FieldSpec(
        "next_action_date",
        "string",
        "Fecha concreta de seguimiento indicada o recomendada por el visitador, "
        "formato YYYY-MM-DD. Vacío sin fecha precisa; no inventes día para plazos vagos.",
    ),
)
VISIT_FIELDS = CORE_FIELDS + DETAIL_FIELDS
FIELD_BY_NAME = {f.name: f for f in VISIT_FIELDS}

DETAILS_DESCRIPTION = (
    "Un objeto JSON válido con los detalles de la PRIMERA visita (V1). "
    "Usa solo información de esa visita, incorpora correcciones y excluye datos identificables "
    "de pacientes. TODAS las claves deben estar presentes. Usa null para datos no mencionados. "
    "Conserva negativas explícitas, pero NO fabriques 'no hubo' o 'no manifestó' por silencio. "
    "El contenido extraído se basa en lo que dijo el VISITADOR, nunca en supuestos del agente. "
    + " ".join(f"{f.name}: {f.description}" for f in DETAIL_FIELDS)
)
CONFIRMATION_DESCRIPTION = "true SOLO si el agente leyó el resumen de ESTA visita, pidió confirmar ese resumen y el visitador respondió explícitamente 'sí', 'correcto' o equivalente. Si corrigió ese resumen, basta mencionar el dato corregido y obtener una nueva confirmación del resumen con ese cambio; no se exige releerlo entero. El cierre normal sin lectura del resumen queda para revisión en la app: 'no tengo nada más', 'nada que corregir', un sí a otra pregunta, silencio, despedida o llamada cortada NO confirma. false si no se leyó un resumen y no hay aceptación explícita posterior."
REQUIRED_REPORT_FIELDS = (
    "products_discussed",
    "visit_objective",
    "discussion",
    "commitment",
    "next_action",
    "receptiveness_score",
    "visit_outcome",
)


def missing_report_fields(fields: dict[str, Any]) -> list[str]:
    structured = fields.get("snc_report_json")
    if structured:
        raw = structured.get("value") if isinstance(structured, dict) else structured.value
        try:
            return SNCReport.model_validate_json(raw).missing()
        except (ValueError, TypeError):
            return ["Reporte estructurado inválido"]

    def value(name: str) -> Any:
        entry = fields.get(name)
        confidence = (
            entry.get("confidence")
            if isinstance(entry, dict)
            else getattr(entry, "confidence", None)
        )
        if confidence == "low":
            return None
        return entry.get("value") if isinstance(entry, dict) else getattr(entry, "value", None)

    if value("visit_outcome") == "not_attended":
        return [] if value("summary") else ["summary"]
    return [name for name in REQUIRED_REPORT_FIELDS if value(name) in (None, "", "unknown")]


GLOBAL_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "report_mode",
        "string",
        "Modalidad elegida explícitamente por el visitador: voice (relato por voz), "
        "written (prefiere escribir en la app), deferred (no tiene tiempo), ongoing "
        "(sigue en la reunión, solo en visit_checkin). Vacío si no lo expresó. "
        "Elegir una modalidad NO confirma un resumen y NO es un dato de la visita.",
    ),
    FieldSpec(
        "meeting_finished",
        "boolean",
        "true SOLO si en visit_checkin dice explícitamente que ya terminó la reunión. "
        "false si sigue reunido o no lo confirmó. No deduzcas el cierre por duración.",
    ),
    FieldSpec(
        "extra_visits_json",
        "string",
        "Solo si en la llamada se reportaron VARIAS visitas: un arreglo JSON con un objeto por "
        "cada visita adicional (V2, V3…), cada uno con la clave 'ref' ('V2', 'V3'…) y las mismas "
        "claves que la primera visita (interest_level, visit_outcome, order_taken, "
        "no_order_reason, receptiveness, objection, competitor, current_preference, commitment, "
        "next_action, next_action_in_days, samples_delivered, products_discussed, "
        "territory_signal, summary), además de los detalles: "
        + ", ".join(f.name for f in DETAIL_FIELDS)
        + ". Añade report_confirmed booleano solo si confirmó el resumen leído de ESA visita. "
        "Nunca uses la confirmación de otro médico. Si solo hubo una visita, "
        "escribe exactamente [].",
    ),
    FieldSpec(
        "uncertain_fields",
        "string",
        "Lista separada por comas de los campos (con el prefijo de su visita, por ejemplo "
        "v1_interest_level) que el visitador no respondió, contestó de forma vaga o que tuviste "
        "que suponer. Usa v1_visit_objective para un detalle, sin details_json ni puntos. "
        "Un dato explícito del relato inicial no se vuelve incierto por una respuesta vaga "
        "posterior a la misma pregunta, salvo que el visitador lo corrija o contradiga. "
        "Vacío si todo quedó claro.",
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
        "true si contó para todas las visitas producto, objetivo, conversación, resultado, "
        "compromisos, próximo paso y receptividad explícita (1–5), o explicó que no se realizó. "
        "Negativas explícitas en compromisos/próximo paso son válidas. No implica confirmación. "
        "false si se cortó o no pudo hablar.",
    ),
)


def data_collection_items() -> dict[str, dict[str, Any]]:
    """Campos que ElevenLabs extrae al terminar (``platform_settings.data_collection``)."""
    items: dict[str, dict[str, Any]] = {}
    for spec in CORE_FIELDS:
        items[f"v1_{spec.name}"] = _item(spec)
    items["v1_details_json"] = {"type": "string", "description": DETAILS_DESCRIPTION}
    items["v1_report_confirmed"] = {"type": "boolean", "description": CONFIRMATION_DESCRIPTION}
    for spec in GLOBAL_FIELDS:
        items[spec.name] = _item(spec)
    return items


def pilot_data_collection_items() -> dict[str, dict[str, Any]]:
    """One structured extraction instead of competing per-field interpretations."""
    return {
        "v1_snc_report_json": {"type":"string", "description":EXTRACTION_DESCRIPTION},
        "v1_summary": {"type":"string", "description":"Resumen fiel de la visita según el visitador, máximo 800 caracteres. Sin datos identificables de pacientes."},
        "v1_report_confirmed": {"type":"boolean", "description":CONFIRMATION_DESCRIPTION},
        "report_mode": {"type":"string", "enum":["voice","written","deferred","ongoing"], "description":"voice por defecto, incluso si faltan datos o no recuerda. written SOLO si el visitador explícitamente decide continuar en la app; deferred si pide parar; ongoing si sigue reunido. No infieras written de campos incompletos. Cambiar canal no borra datos narrados."},
        "meeting_finished": {"type":"boolean", "description":"true solo si terminó la visita o dice explícitamente que ya terminó."},
        "interview_complete": {"type":"boolean", "description":"true solo si informó productos/orden, objetivos/resultados, barreras, direccionamiento y compromisos (incluidas negativas explícitas). Confirmación y completitud son distintas."},
    }


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
    complete: bool  # tiene los datos esenciales del reporte
    problems: list[str]  # campos descartados por inválidos
    confirmed: bool = False


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
    "doctor_commitment": 500,
    "representative_commitment": 500,
    "location_change_reason": 500,
    "next_visit_objective": 300,
    "commitment_due_date": 10,
    "objection": 500,
    "competitor": 80,
    "current_preference": 120,
    "commitment": 500,
    "next_action": 300,
    "products_discussed": 160,
    "territory_signal": 200,
    "summary": 800,
    "visit_objective": 300,
    "discussion": 1000,
    "doctor_interest": 500,
    "doctor_disinterest": 500,
    "doctor_reaction": 500,
    "new_information": 700,
    "free_note": 700,
    "next_action_date": 10,
}


def _coerce(spec: FieldSpec, raw: Any) -> Any:
    """Devuelve el valor limpio o lanza ``ValueError`` si es inválido."""
    if raw is None:
        return None
    if spec.name == "snc_report_json":
        return normalize_report(raw)
    if spec.type == "integer":
        if isinstance(raw, bool):
            raise ValueError("entero esperado")
        try:
            numeric = float(str(raw).strip())
            number = int(numeric)
            if numeric != number:
                raise ValueError("entero esperado")
        except (TypeError, ValueError, OverflowError):
            raise ValueError("entero esperado") from None
        if spec.name in ("interest_level", "receptiveness_score"):
            if number == 0:
                return None  # 0 = no determinado
            if not 1 <= number <= 5:
                raise ValueError("interés fuera de 1–5")
        if spec.name == "next_action_in_days":
            if number == 0:
                return None
            if not 1 <= number <= 730:
                raise ValueError("plazo fuera de rango")
        if spec.name == "commitment_quantity" and not 1 <= number <= 100000:
            raise ValueError("cantidad fuera de rango")
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
    if spec.name in ("next_action_date", "commitment_due_date") and raw:
        if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw.strip()):
            raise ValueError("fecha esperada")
        return date.fromisoformat(raw.strip()).isoformat()
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
    fields: set[str] = set()
    for part in re.split(r"[,;\n]", raw):
        key = part.strip().lower()
        if not key:
            continue
        # El proveedor también devuelve rutas de detalles como v1_details_json.visit_objective.
        match = re.fullmatch(r"(v[1-5])(?:[_.]details_json)?[_.](\w+)", key)
        if match and match[2] in FIELD_BY_NAME:
            key = f"{match[1]}_{match[2]}"
        fields.add(key)
    return fields


def _visit_from_mapping(position: int, get: Any, prefix: str, uncertain: set[str]) -> ParsedVisit:
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
    # Flags del proveedor por sí solos no son una entrevista.
    if not any(
        name not in {"order_taken", "samples_delivered", "no_order_reason", "receptiveness"}
        for name in fields
    ):
        fields = {}
    confirmed = _raw_value(get("report_confirmed")) is True
    return ParsedVisit(
        position=position,
        fields=fields,
        complete=not missing_report_fields(fields),
        problems=problems,
        confirmed=confirmed,
    )


def parse_analysis(results: dict[str, Any], visit_count: int) -> list[ParsedVisit]:
    """Convierte ``analysis.data_collection_results`` en una ficha por visita (posición 1…N).

    Nunca lanza: una visita sin datos válidos devuelve una ficha vacía (``complete=False``).
    """
    uncertain = _uncertain(_clean_text(_raw_value(results.get("uncertain_fields")), 800))
    details_raw = _raw_value(results.get("v1_details_json"))
    bad_details = False
    try:
        details = (
            json.loads(details_raw)
            if isinstance(details_raw, str) and details_raw
            else details_raw or {}
        )
        if not isinstance(details, dict):
            raise ValueError("objeto esperado")
    except (TypeError, ValueError):
        details, bad_details = {}, True
    first = _visit_from_mapping(
        1, lambda name: _raw_value(results.get(f"v1_{name}", details.get(name))), "v1_", uncertain
    )
    if bad_details:
        first.problems.append("details_json")
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


def report_mode(results: dict[str, Any]) -> str | None:
    value = _raw_value(results.get("report_mode"))
    return value if value in ("voice", "written", "deferred", "ongoing") else None


def meeting_finished(results: dict[str, Any]) -> bool:
    return _raw_value(results.get("meeting_finished")) is True
