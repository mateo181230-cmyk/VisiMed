"""A transparent provisional rating of reported objective progress, not medical quality."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from uno.modules.calls.models import VisitReport
from uno.modules.journey.schema import FeedbackCriterionOut, FeedbackOut

RUBRIC_VERSION = "objective-progress-v1"
RUBRIC_DESCRIPTION = (
    "Calificación provisional del avance declarado: objetivo logrado 10/10, avance parcial "
    "5/10 y objetivo no logrado 0/10. Sin evidencia explícita no se asigna nota. "
    "El cumplimiento del pendiente del visitador y la precisión del cierre se muestran aparte."
)


def evidence(report: VisitReport | None, name: str) -> Any:
    entry = (report.fields or {}).get(name) if report else None
    if not isinstance(entry, dict) or entry.get("confidence") == "low":
        return None
    value = entry.get("value")
    if isinstance(value, str):
        value = value.strip()
        if not value or value.lower() in ("unknown", "null", "none"):
            return None
    return value


def text_evidence(report: VisitReport | None, name: str) -> str | None:
    value = evidence(report, name)
    return value[:2000] if isinstance(value, str) else None


def feedback_for(visit_id: uuid.UUID, report: VisitReport | None) -> FeedbackOut:
    progress = evidence(report, "objective_progress")
    scores = {"achieved": 10, "partial": 5, "not_achieved": 0}
    score = scores.get(progress) if isinstance(progress, str) else None
    bands = {
        "achieved": "Objetivo logrado",
        "partial": "Avance parcial",
        "not_achieved": "Objetivo no logrado",
    }
    band = (
        bands.get(progress, "Pendiente de valorar")
        if isinstance(progress, str)
        else "Pendiente de valorar"
    )
    reasons = {
        "achieved": "El reporte declara que se logró el objetivo de la visita.",
        "partial": "El reporte declara un avance parcial; aún queda por concretar el objetivo.",
        "not_achieved": "El reporte declara que no se logró el objetivo en esta visita.",
    }
    unknown = "El reporte no permite determinar el avance del objetivo con suficiente certeza."
    why = reasons.get(progress, unknown) if isinstance(progress, str) else unknown
    if report is None:
        why = "El resumen de esta visita todavía no está disponible."
    elif report.status != "confirmed":
        why += " Revisa y confirma el resumen para validar la información."

    quantity = evidence(report, "commitment_quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        quantity = None
    due = text_evidence(report, "commitment_due_date")
    if due:
        try:
            due = date.fromisoformat(due).isoformat()
        except ValueError:
            due = None
    fulfilled = evidence(report, "previous_commitment_fulfilled")
    if fulfilled not in ("yes", "partial", "no"):
        fulfilled = None
    doctor_commitment = text_evidence(report, "doctor_commitment")
    next_objective = text_evidence(report, "next_visit_objective")
    if not next_objective:
        next_objective = (
            "Confirmar la experiencia con el compromiso acordado y definir el siguiente paso."
            if doctor_commitment
            else "Acordar con el médico una acción concreta y cómo darle seguimiento."
        )
    if score is None:
        advice = (
            "Completa o aclara en tu resumen qué avance tuvo el objetivo "
            "antes de valorar el resultado."
        )
    elif score == 10:
        advice = (
            "Retoma el acuerdo en la próxima visita y verifica qué ocurrió "
            "antes de proponer otro paso."
        )
    elif doctor_commitment:
        advice = (
            "Convierte el interés en una acción específica y acuerda cuándo revisarla. "
            "Si el objetivo requiere una cantidad, confirma también cuántos casos o unidades."
        )
    else:
        advice = (
            "Retoma la principal barrera y acuerda un próximo paso que el médico pueda confirmar."
        )
    return FeedbackOut(
        visit_id=visit_id,
        score=score,
        band=band,
        why=why,
        rubric_version=RUBRIC_VERSION,
        rubric_description=RUBRIC_DESCRIPTION,
        report_status=report.status if report else None,
        report_updated_at=report.updated_at if report else None,
        summary=text_evidence(report, "summary"),
        new_information=text_evidence(report, "new_information"),
        barrier=text_evidence(report, "objection"),
        competitor=text_evidence(report, "competitor"),
        doctor_commitment=doctor_commitment,
        rep_commitment_fulfilled=fulfilled,
        commitment_quantity=quantity,
        commitment_due_date=due,
        next_objective=next_objective,
        advice=advice,
        criteria=[
            FeedbackCriterionOut(
                key="objective_progress",
                label="Avance del objetivo",
                value=progress if isinstance(progress, str) else None,
                evidence_field="objective_progress",
            ),
            FeedbackCriterionOut(
                key="pending_commitment",
                label="Tu compromiso anterior",
                value=fulfilled,
                evidence_field="previous_commitment_fulfilled",
            ),
            FeedbackCriterionOut(
                key="quantity",
                label="Cantidad acordada, si aplica",
                value=quantity,
                evidence_field="commitment_quantity",
            ),
            FeedbackCriterionOut(
                key="due_date",
                label="Fecha acordada",
                value=due,
                evidence_field="commitment_due_date",
            ),
        ],
    )
