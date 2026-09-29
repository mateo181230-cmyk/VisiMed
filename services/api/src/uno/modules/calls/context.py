"""Lo que UNO le cuenta al agente de voz antes de cada llamada (variables dinámicas).

El agente no consulta nuestra base: recibe, ya redactado en español hablado, quién es el visitador
y de qué visitas debe informar. Por privacidad (Q15, pendiente de legal) el nombre del médico solo
viaja si ``include_doctor_names`` está activo; si no, la visita se nombra por hora e institución.
Nunca viajan pacientes, documentos ni celulares de médicos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from uno import clock
from uno.modules.calls.schema import MAX_VISITS_PER_CALL


@dataclass(frozen=True)
class VisitBrief:
    doctor_name: str
    institution: str | None
    line_code: str
    scheduled_at: datetime  # la hora agendada; el visitador la reconoce mejor que la del toque
    arrived_at: datetime | None = None


def first_name(full_name: str) -> str:
    """Nombre de pila para saludar («Ana María Pérez» → «Ana»)."""
    parts = full_name.strip().split()
    return parts[0] if parts else "colega"


_TITLES = {
    "dra": "la doctora",
    "dr": "el doctor",
    "doctora": "la doctora",
    "doctor": "el doctor",
    "dr.": "el doctor",
    "dra.": "la doctora",
}


def doctor_phrase(full_name: str) -> str:
    """«Dra. Laura Méndez» → «la doctora Laura Méndez»; sin título, solo el nombre."""
    name = re.sub(r"\s+", " ", full_name).strip()
    head, _, rest = name.partition(" ")
    title = _TITLES.get(head.lower().rstrip("."))
    if title and rest:
        return f"{title} {rest}"
    return name


def spoken_time(when: datetime, tz_name: str) -> str:
    """Hora dicha como se habla en Colombia: «las 9:30 de la mañana», «la 1 de la tarde»."""
    local = when.astimezone(clock.tz(tz_name))
    hour, minute = local.hour, local.minute
    hour12 = hour % 12 or 12
    if hour < 12:
        period = "de la mañana"
    elif hour == 12:
        period = "del día"
    elif hour < 18:
        period = "de la tarde"
    else:
        period = "de la noche"
    if hour12 == 1:
        clock_text = "una" if minute == 0 else f"1:{minute:02d}"
        return f"la {clock_text} {period}"
    clock_text = f"{hour12}" if minute == 0 else f"{hour12}:{minute:02d}"
    return f"las {clock_text} {period}"


def _where(institution: str | None) -> str:
    return f" en {institution}" if institution else ""


def visit_label(brief: VisitBrief, tz_name: str, include_names: bool) -> str:
    """Cómo se nombra una visita en voz alta: «la doctora X» o «la visita de las 9:30 en Y»."""
    if include_names:
        return f"la visita con {doctor_phrase(brief.doctor_name)}"
    return f"la visita de {spoken_time(brief.scheduled_at, tz_name)}{_where(brief.institution)}"


def short_label(brief: VisitBrief, tz_name: str, include_names: bool) -> str:
    """Forma corta para enumerar: «la de la doctora X», «la del doctor X», «la de las 9:30 en Y»."""
    if include_names:
        who = doctor_phrase(brief.doctor_name)
        return "la del " + who[3:] if who.startswith("el ") else f"la de {who}"
    return f"la de {spoken_time(brief.scheduled_at, tz_name)}{_where(brief.institution)}"


def _first_question(brief: VisitBrief, tz_name: str, include_names: bool) -> str:
    if include_names:
        return f"¿Cómo te fue con {doctor_phrase(brief.doctor_name)}?"
    return f"¿Cómo te fue en {visit_label(brief, tz_name, False)}?"


def build_dynamic_variables(
    representative_name: str,
    visits: list[VisitBrief],
    *,
    tz_name: str,
    include_names: bool,
) -> dict[str, str]:
    """Variables del agente (``infra/elevenlabs/agent.json``): saludo, visitas y pregunta."""
    if not visits:
        raise ValueError("Una llamada necesita al menos una visita")
    visits = visits[:MAX_VISITS_PER_CALL]

    lines = []
    for index, brief in enumerate(visits, start=1):
        who = f" con {doctor_phrase(brief.doctor_name)}" if include_names else ""
        lines.append(
            f"{index}. La visita de {spoken_time(brief.scheduled_at, tz_name)}{who}"
            f"{_where(brief.institution)} (línea {brief.line_code})."
        )

    if len(visits) == 1:
        opening = _first_question(visits[0], tz_name, include_names)
    else:
        first = short_label(visits[0], tz_name, include_names)
        opening = (
            f"Tengo {len(visits)} visitas tuyas por reportar. Empecemos con {first}: "
            "¿cómo te fue?"
        )
    return {
        "visitador_nombre": first_name(representative_name),
        "num_visitas": str(len(visits)),
        "visitas_texto": "\n".join(lines),
        "pregunta_inicial": opening,
    }
