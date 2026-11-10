"""Structured facts from a visit. Null is unknown; [] is an explicit absence."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Fact(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ProductFact(Fact):
    position: int | None = Field(default=None, ge=1, le=5)
    name: str = Field(min_length=1, max_length=100)
    objective: str | None = Field(default=None, max_length=500)
    metric: str | None = Field(default=None, max_length=180)
    target: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    unit: str | None = Field(default=None, max_length=60)
    due_date: date | None = None
    due_text: str | None = Field(default=None, max_length=180)
    achievement: Literal["achieved", "partial", "not_achieved", "unknown"] = "unknown"
    evidence: str | None = Field(default=None, max_length=800)
    barriers: list[str] | None = Field(default=None, max_length=5)

    @model_validator(mode="after")
    def facts_need_evidence(self):
        if self.achievement in ("achieved", "partial") and not self.evidence:
            self.achievement = "unknown"
        if self.barriers and any(not x.strip() or len(x) > 500 for x in self.barriers):
            raise ValueError("Barrera vacía o demasiado larga")
        return self


class ReferralFact(Fact):
    destination: str = Field(min_length=1, max_length=240)
    # The destination can be known while the associated brands are not. Preserve
    # that partial evidence rather than rejecting every fact in the interview.
    products: list[str] | None = Field(default=None, max_length=5)


class CommitmentFact(Fact):
    owner: Literal["doctor", "representative", "unknown"] = "unknown"
    action: str = Field(min_length=1, max_length=500)
    due_date: date | None = None
    due_text: str | None = Field(default=None, max_length=180)
    next_objective: str | None = Field(default=None, max_length=500)


class SNCReport(Fact):
    schema_version: Literal["snc-1"] = "snc-1"
    products: list[ProductFact] = Field(default_factory=list, max_length=5)
    referrals: list[ReferralFact] | None = Field(default=None, max_length=10)
    commitments: list[CommitmentFact] | None = Field(default=None, max_length=10)
    not_attended_reason: str | None = Field(default=None, max_length=500)
    sequence_evidence: str | None = Field(default=None, max_length=700)
    referrals_evidence: str | None = Field(default=None, max_length=700)
    commitments_evidence: str | None = Field(default=None, max_length=700)

    @model_validator(mode="after")
    def unique_sequence(self):
        positions = [p.position for p in self.products if p.position is not None]
        if positions and positions != list(range(1, len(positions) + 1)):
            raise ValueError("El orden real debe ser único y consecutivo")
        if len({p.name.casefold() for p in self.products}) != len(self.products):
            raise ValueError("Producto duplicado")
        if self.not_attended_reason and self.products:
            raise ValueError("Una visita no realizada no puede tener productos presentados")
        names = {p.name.casefold() for p in self.products}
        if any(n.casefold() not in names for r in self.referrals or [] for n in r.products or []):
            raise ValueError("Direccionamiento de un producto no presentado")
        return self

    def missing(self) -> list[str]:
        missing = []
        if not self.products and not self.not_attended_reason:
            missing.append("Productos y orden")
        for p in self.products:
            if p.position is None:
                missing.append(f"{p.name}: Orden real")
            for label, value in [("Objetivo", p.objective), ("Medida y plazo SMART", p.metric and p.target is not None and p.unit and p.due_date), ("Resultado", p.achievement != "unknown"), ("Barreras", p.barriers is not None)]:
                if not value:
                    missing.append(f"{p.name}: {label}")
        if self.referrals is None and not self.not_attended_reason:
            missing.append("Droguería de destino")
        for referral in self.referrals or []:
            if not referral.products:
                missing.append(f"{referral.destination}: Productos direccionados")
        if self.commitments is None:
            missing.append("Compromisos")
        return missing


def normalize_report(raw) -> str:
    if isinstance(raw, str):
        if len(raw) > 24000:
            raise ValueError("Reporte demasiado largo")
        raw = json.loads(raw)
    report = SNCReport.model_validate(raw)
    return report.model_dump_json()


def ground_report(raw: str, user_text: str, reference_date: date | None = None) -> str:
    """Only an explicit, source-backed absence can become an empty list."""
    report = SNCReport.model_validate_json(raw)
    def normal(t):
        return re.sub(r"\s+", " ", ''.join(c for c in unicodedata.normalize('NFD', t.lower()) if unicodedata.category(c) != 'Mn')).strip()
    transcript = normal(user_text)
    if re.search(r"no (?:recuerdo|recuerda|se)[^.!?]{0,100}\bbarrera", transcript):
        for p in report.products:
            if p.barriers == []:
                p.barriers = None
    def quoted(e):
        return bool(e and len(e.strip()) >= 5 and normal(e) in transcript)
    if not quoted(report.sequence_evidence) or re.search(r"no recuerdo.*orden|no se.*orden", normal(report.sequence_evidence or "")):
        for p in report.products:
            p.position = None
    if report.referrals == [] and not quoted(report.referrals_evidence):
        report.referrals = None
    if report.commitments == [] and not quoted(report.commitments_evidence):
        report.commitments = None
    if report.commitments:
        evidence = normal(report.commitments_evidence or "")
        # A request is not an accepted promise. Unsubstantiated actions remain
        # unknown for human review instead of entering next-visit planning.
        request_only = bool(re.search(r"\b(pidio|solicito|pide|solicita)\b", evidence)) and not re.search(
            r"\b(acordamos|acordo|quede|quedamos|quedo pendiente|comprometi|comprometio|acepte|acepto|enviare|enviara|llevare|llevara|hare|hara|voy a|va a|vamos a|enviar[eá])\b", evidence
        )
        if not quoted(report.commitments_evidence) or request_only:
            report.commitments = None
    for fact in [*report.products, *(report.commitments or [])]:
        # Simulation/provider clocks are not the commercial calendar. Resolve only
        # unambiguous, quoted relative dates against the real call date in Bogotá.
        due = normal(fact.due_text or "")
        if due and due in transcript and reference_date and due in ("manana", "hoy", "pasado manana"):
            fact.due_date = reference_date + timedelta(days={"hoy":0,"manana":1,"pasado manana":2}[due])
        elif fact.due_date and fact.due_date.isoformat() not in user_text:
            fact.due_date = None
    return report.model_dump_json()


def legacy_projection(data: SNCReport) -> dict[str, str]:
    values = {
        "products_discussed": ", ".join(x.name for x in data.products),
        "visit_objective": "; ".join(f"{x.name}: {x.objective}" for x in data.products if x.objective),
        "objection": "; ".join(f"{x.name}: {', '.join(x.barriers)}" for x in data.products if x.barriers),
        "commitment": "; ".join(x.action for x in data.commitments or []) if data.commitments else ("No quedaron compromisos" if data.commitments == [] else ""),
        "next_action": "; ".join(x.action for x in data.commitments or [] if x.owner == "representative"),
        "discussion": "; ".join(f"{x.name}: {x.evidence}" for x in data.products if x.evidence),
    }
    if data.not_attended_reason:
        values.update(visit_outcome="not_attended",discussion=data.not_attended_reason)
    return values


EXTRACTION_DESCRIPTION = """Devuelve UN JSON, sin markdown, SOLO con lo declarado por el visitador en esta reunión. Nombres y valores son ejemplos de formato; usa null si no se sabe y conserva correcciones.
Esquema COMPLETO:
{"schema_version":"snc-1","sequence_evidence":null,"products":[{"position":1,"name":"MARCA","objective":null,"metric":null,"target":null,"unit":null,"due_date":null,"due_text":null,"achievement":"unknown","evidence":null,"barriers":null}],"referrals":null,"referrals_evidence":null,"commitments":null,"commitments_evidence":null,"not_attended_reason":null}.
products son hasta cinco marcas realmente presentadas, EN ORDEN. sequence_evidence es la cita EXACTA del visitador que enumera las marcas o dice que fue una sola. Si no recuerda el orden: position=null, sin inventarlo.
achievement: achieved|partial|not_achieved|unknown. Exige evidencia explícita para achieved o partial. No confundir interés con venta. Si el objetivo era conocer una duda y dijo que la identificó, achieved aunque haya barrera comercial. objective conserva las palabras y target las cantidades explícitas (dos casos=2; unit=casos). Nunca copiar el objetivo planeado como evidencia de logro.
barriers es lista de textos vinculados a esa marca. [] solo cuando negó barreras; null si no habló de ellas.
Una solicitud de material NO es automáticamente barrera ni compromiso. «Quería mostrar evidencia; pidió un artículo» significa objective="mostrar evidencia", evidence="pidió un artículo", achievement="unknown", barriers=null, commitments=null salvo aceptación explícita posterior.
referrals: [{"destination":"nombre y sede","products":["MARCA"]}], [] si negó direccionamientos, null si no se sabe. referrals_evidence: cita EXACTA que lo respalda, no paráfrasis.
commitments: [{"owner":"representative","action":"enviar el estudio","due_date":null,"due_text":"mañana","next_objective":null}]. owner es doctor|representative|unknown. Extrae TODAS las acciones prometidas, tanto del visitador como del médico. Si el visitador enviará estudios y el médico no se comprometió, CONSERVA enviar estudios con owner=representative; no uses []. commitments_evidence: cita EXACTA de la promesa o de que no quedaron pendientes. [] solo si se negó todo compromiso; null si no preguntó o no recuerda.
due_date SOLO para fechas ISO explícitas del relato; NO CALCULES fechas relativas ni uses el reloj de la simulación. Para mañana/hoy/esta semana/pronto usa due_text textual y due_date=null. El servidor resolverá fechas inequívocas.
Si se cortó/eligió app, conserva hechos narrados, sin inventar negativas ni confirmación. Si no hubo visita products=[] y not_attended_reason=motivo declarado. Sin datos identificables de pacientes. TODAS las claves del esquema deben estar presentes en su nivel correcto."""
