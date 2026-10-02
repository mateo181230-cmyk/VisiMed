"""Del transcript al resultado que ve el visitador (doc 04 §5.9, pasos 3 y 4).

Hoy la calificación sale de las reglas (``method = "reglas"``) y se presenta como **preliminar**.
Cuando haya juez LLM, este módulo recibirá también su salida; las reglas siguen marcando lo que el
juez no puede omitir (por ejemplo, una cifra sin soporte).
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from uno.modules.training import rules
from uno.modules.training.content import Catalog, Scenario
from uno.modules.training.rubric import (
    BAND_FEEDBACK,
    CASE_CHECKS,
    COMPETENCIES,
    COMPETENCY_NAME,
    CRITICAL_ERRORS,
    MAX_PER_COMPETENCY,
    MAX_TOTAL,
    REMEDIATION,
    RUBRIC_VERSION,
    band_for,
)

PASS_QUIZ_RATIO = 0.75  # preparación aprobada: 3 de 4 (prototipo de Sangil)
BASIC_COMPETENCIES = frozenset(("apertura", "argumentacion", "cierre"))
BASIC_BAND_LABELS = frozenset(("Presentación inicial lograda", "Presentación inicial por reforzar"))


def for_display(result: dict[str, Any]) -> dict[str, Any]:
    """Completa metadatos de resultados anteriores sin recalificar ni reescribirlos.

    El rótulo del nivel básico quedó guardado con la evaluación v2. Se usa esa señal
    histórica, nunca la dificultad actual del catálogo, que puede cambiar después.
    """
    display = deepcopy(result)
    introductory = display.get("band", {}).get("label") in BASIC_BAND_LABELS
    for competency in display.get("competencies", []):
        competency.setdefault(
            "evaluated", not introductory or competency["id"] in BASIC_COMPETENCIES
        )
    return display


@dataclass(frozen=True)
class QuizSnapshot:
    correct: int
    total: int

    @property
    def passed(self) -> bool:
        return self.total > 0 and self.correct / self.total >= PASS_QUIZ_RATIO


def adapt_salutation(text: str, scenario: Scenario) -> str:
    """El banco dice «doctor»; si la médica del escenario es mujer, se dice «doctora»."""
    if scenario.doctor.gender != "F":
        return text
    return re.sub(r"\b([Dd])octor\b", lambda m: f"{m.group(1)}octora", text)


def assess(
    scenario: Scenario,
    scores: dict[str, int],
    total: int,
    errors: list[str],
    areas: list[str],
    quiz: QuizSnapshot | None,
) -> dict[str, Any]:
    """¿Aprobó el escenario? Requisitos del escenario (PROPUESTA; decisión D9 de Novamed)."""
    rule = scenario.approval
    requirements = [
        {
            "id": "total",
            "text": f"Puntaje total mínimo: {rule.min_total}/{MAX_TOTAL}",
            "met": total >= rule.min_total,
        }
    ]
    requirements += [
        {
            "id": competency,
            "text": f"{COMPETENCY_NAME[competency]}: mínimo {minimum}/{MAX_PER_COMPETENCY}",
            "met": scores.get(competency, 0) >= minimum,
        }
        for competency, minimum in rule.min_competencies.items()
    ]
    requirements.append(
        {
            "id": "errores",
            "text": "Sin errores críticos propios de este escenario",
            "met": not any(e in errors for e in rule.blocking_errors),
        }
    )
    approved = all(r["met"] for r in requirements)
    if quiz is None:
        diagnosis = (
            "Aplicaste la técnica en conversación."
            if approved
            else (
                "Aún no sostienes la técnica en conversación: repasa la preparación y vuelve a "
                "intentarlo."
            )
        )
    elif approved and quiz.passed:
        diagnosis = (
            "Dominio demostrado: comprendiste la técnica y lograste aplicarla en conversación."
        )
    elif approved:
        diagnosis = (
            "Ejecución intuitiva: lograste aplicarla, pero conviene consolidar el fundamento."
        )
    elif quiz.passed:
        diagnosis = (
            "Brecha de ejecución: reconoces la técnica, pero aún no la sostienes bajo presión."
        )
    else:
        diagnosis = (
            "Brecha de fundamento y ejecución: necesitas repasar la técnica y volver a practicarla."
        )
    failed = [r["id"] for r in requirements if not r["met"] and r["id"] in REMEDIATION]
    focus = (failed or areas or ["argumentacion"])[0]
    return {
        "approved": approved,
        "requirements": requirements,
        "diagnosis": diagnosis,
        "focus": focus,
        "practice": REMEDIATION[focus],
    }


def build(
    catalog: Catalog,
    scenario: Scenario,
    turns: list[rules.Turn],
    quiz: QuizSnapshot | None,
) -> dict[str, Any]:
    """Evaluación completa y lista para mostrar. Todo texto sobre el producto sale del banco."""
    introductory = scenario.difficulty == "basico"
    result = rules.evaluate(turns, scenario.slug, introductory=introductory)
    total = sum(result.scores.values())
    band = band_for(total)
    # Con 3 o más errores críticos no puede ser «sobresaliente» (prototipo, `index.js`).
    if len(result.errors) >= 3 and band.level == "sobresaliente":
        band = band_for(19)
    assessment = assess(scenario, result.scores, total, result.errors, result.areas, quiz)
    best = catalog.bank.best_for(assessment["focus"], scenario)
    critical = [
        {"id": e, "text": CRITICAL_ERRORS[e][0], "kind": CRITICAL_ERRORS[e][1]}
        for e in result.errors
    ]
    critical.sort(key=lambda e: e["kind"] != "compliance")  # cumplimiento primero
    improvements = result.improvements
    if improvements == [rules.DEFAULT_IMPROVEMENT]:
        # Ninguna competencia quedó en 2 o menos: se señala la más baja, si no está completa.
        assessed = tuple(c for c in COMPETENCIES if not introductory or c.id in BASIC_COMPETENCIES)
        lowest = min(assessed, key=lambda c: result.scores[c.id])
        if result.scores[lowest.id] < MAX_PER_COMPETENCY:
            improvements = [f"{lowest.name}: {result.comments[lowest.id]}"]
        else:
            improvements = []
    return {
        "method": "reglas",
        "preliminary": True,
        "total": total,
        "max": MAX_TOTAL,
        "band": {
            "level": band.level,
            "label": (
                "Presentación inicial lograda"
                if assessment["approved"]
                else "Presentación inicial por reforzar"
            )
            if introductory
            else band.label,
        },
        "competencies": [
            {
                "id": c.id,
                "name": c.name,
                "score": result.scores[c.id],
                "max": MAX_PER_COMPETENCY,
                "comment": result.comments[c.id],
                "evaluated": not introductory or c.id in BASIC_COMPETENCIES,
            }
            for c in COMPETENCIES
        ],
        "critical_errors": critical,
        "case_checks": [
            {"id": check_id, "text": text, "value": result.checks[check_id]}
            for check_id, text in CASE_CHECKS
            if not introductory or check_id == "posiciono_principio_activo"
        ],
        "strengths": result.strengths[:2],
        "improvements": improvements[:2],
        "recommendation": result.recommendation,
        "key_moment": result.key_moment,
        "best_response": (
            {
                "id": best.id,
                "text": adapt_salutation(best.text, scenario),
                "source": best.source,
                "area": COMPETENCY_NAME.get(best.area, best.area),
            }
            if best
            else None
        ),
        "feedback": (
            (
                "Lograste una primera presentación breve y correcta. "
                "Practica ahora con un médico que plantee una duda sencilla."
                if assessment["approved"]
                else "Refuerza el saludo, el principio activo y una idea breve "
                "para un perfil de paciente. "
                "No necesitas estudios ni objeciones en este nivel."
            )
            if introductory
            else BAND_FEEDBACK[band.level]
        ),
        "training": assessment,
        "quiz": {"correct": quiz.correct, "total": quiz.total} if quiz else None,
        "turns": len(turns),
        "versions": {"rubric": RUBRIC_VERSION, "rules": rules.RULES_VERSION},
    }
