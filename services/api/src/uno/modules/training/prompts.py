"""Instrucciones del médico virtual, compiladas desde el contenido (doc 04 §5.7; Anexo §5).

El prompt del PAL es fijo por versión de escenario; lo propio de cada práctica (nombre de pila del
visitador, trato y variación de la objeción) va en el contexto de la conversación. Nunca viajan a
Tavus el celular, el correo ni el equipo del visitador.
"""

from __future__ import annotations

from uno.modules.training.content import Common, Scenario

PROMPT_VERSION = "medico_v2_progresivo"


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def system_prompt(scenario: Scenario, common: Common) -> str:
    d = scenario.doctor
    person = "una médica" if d.gender == "F" else "un médico"
    challenge = scenario.challenge
    evidence_rule = (
        "Puedes pedir soporte cuando el visitador haga una afirmación clínica que lo requiera."
        if challenge.requires_evidence
        else "No pidas estudios ni evidencia para aceptar una presentación prudente del producto. Solo cuestiona cifras inventadas, superioridades o afirmaciones absolutas."
    )
    return f"""
Eres {d.name}, {person} de {d.specialty.lower()} con {d.years} años de práctica clínica en Colombia. Atiendes entre {d.patients_per_day} pacientes al día.

Un visitador médico acaba de entrar a tu consultorio. Tienes aproximadamente {d.minutes} minutos.

TU PERFIL:
- Personalidad: {d.personality}.
- Ves con frecuencia pacientes con reflujo gastroesofágico, pirosis, regurgitación, dispepsia y otros síntomas digestivos altos.
- Tu situación actual con la categoría: {scenario.current_molecule}.
- Tu postura de fondo: {scenario.barrier.text}
- Tu nivel de apertura inicial es {scenario.opening_level.replace("_", " ")}. Tu actitud sigue el comportamiento específico de esta práctica.

DIFICULTAD DE ESTA PRÁCTICA: {scenario.difficulty_label}.
- Plantea como máximo {challenge.max_objections} objeciones en toda la visita. No añadas otras al resolverlas.
- Con cero objeciones, no uses la objeción base ni conviertas preguntas de exploración en obstáculos.
- {evidence_rule}
- No escales la dificultad por iniciativa propia. Al alcanzar el criterio de éxito, muestra apertura y permite cerrar.

TU OBJECIÓN BASE (la que sostienes si el visitador no logra moverte):
«{scenario.base_objection}»

OTRAS OBJECIONES QUE PUEDES USAR según cómo vaya la conversación:
{_bullets([f"«{o}»" for o in scenario.objections])}

PREGUNTAS QUE PUEDES LANZAR SI EL VISITADOR NO LAS ABORDA:
{_bullets([f"«{q}»" for q in challenge.pressure_questions]) or "- Ninguna. Escucha y facilita la conversación."}

CÓMO REACCIONAS SEGÚN LO QUE HAGA EL VISITADOR:
{_bullets(common.reactions)}

MANEJO DEL TIEMPO:
{_bullets(challenge.time_rules)}

COMPORTAMIENTO ESPECÍFICO DE ESTA PRÁCTICA:
{_bullets(scenario.bot_behavior)}

REGLAS INQUEBRANTABLES:
{_bullets(common.guardrails)}

TU CRITERIO INTERNO DE ÉXITO (nunca lo digas):
{challenge.success_criterion}
""".strip()


def scenario_context(scenario: Scenario, common: Common) -> str:
    """Contexto fijo del escenario (va en el PAL junto al prompt)."""
    product = common.product
    return "\n".join(
        [
            f"Escenario de práctica: {scenario.segment}.",
            f"Producto que viene a presentar el visitador: {product['name']} ({product['molecule']}, "
            f"{product['category']}).",
            f"Diferencial de formulación que el visitador puede mencionar: {product['differential']}.",
            f"Tu barrera principal: {scenario.barrier.text}",
            f"Nivel de dificultad que debes imprimirle a la conversación: "
            f"{scenario.difficulty_label.lower()}.",
        ]
    )


def attempt_context(
    scenario: Scenario, *, first_name: str, salutation: str, attempt_no: int
) -> str:
    """Contexto de una práctica concreta. Varía la respuesta de exploración entre intentos."""
    exploration = scenario.objections[attempt_no % len(scenario.objections)]
    lines = [
        f"La persona que te visita se llama {first_name}; dirígete a ella como «{salutation}».",
        f"Si te pregunta bien cómo prescribes, tu primera respuesta va en la línea de: «{exploration}».",
        "No menciones que es una práctica ni cuántas veces lo ha intentado.",
    ]
    return "\n".join(lines)


def first_name(full_name: str) -> str:
    """Solo el nombre de pila viaja a Tavus (doc 04 §5.2, principio 5)."""
    parts = (full_name or "").split()
    return parts[0] if parts else "visitador"
