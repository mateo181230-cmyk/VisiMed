"""Visit-specific preparation and source-backed learning, independent of video avatars."""
from __future__ import annotations

import hashlib
import random
import re
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select

from uno import clock
from uno.errors import ApiError
from uno.modules.agenda.models import Visit
from uno.modules.calls.brands import catalogue
from uno.modules.calls.models import VisitReport
from uno.modules.calls.snc_report import SNCReport
from uno.modules.catalog.models import Institution
from uno.modules.journey.service import previous_report
from uno.modules.territory.service import owner
from .knowledge import retrieve, check_line
from .models import VisitLearning


class Objective(BaseModel):
    product_id: uuid.UUID
    objective: str = Field(min_length=8, max_length=500)
    measure: str = Field(default="", max_length=200)
    due: str = Field(default="", max_length=100)


class Plan(BaseModel):
    visit_id: uuid.UUID
    objectives: list[Objective] = Field(max_length=5)


class Answer(BaseModel):
    visit_id: uuid.UUID
    lesson_id: str = Field(max_length=64)
    answer: str = Field(min_length=1, max_length=100)


class Reflection(BaseModel):
    visit_id: uuid.UUID
    lesson_id: str = Field(max_length=64)
    text: str = Field(min_length=20, max_length=1500)


async def own_visit(session, actor, id, write=False):
    visit = await session.get(Visit, id)
    if not visit:
        raise ApiError(404, "missing_visit", "No encontramos la visita")
    from uno.modules.auth.permissions import require_visit_read
    require_visit_read(actor, visit)
    check_line(actor, visit.primary_line_id)
    if write and actor.id != visit.representative_id:
        raise ApiError(403, "own_learning", "La preparación y las respuestas pertenecen al visitador")
    return visit


def facts(report):
    raw = (report.fields or {}).get("snc_report_json", {}).get("value") if report else None
    return SNCReport.model_validate_json(raw) if raw else None


def make_lesson(source):
    """An extractive cloze: tests reading without inventing medical assertions."""
    text = source["excerpt"]
    words = list(dict.fromkeys(re.findall(r"\b[a-záéíóúñ]{8,}\b", text, re.I)))
    if len(words) < 3:
        return None
    chosen = words[0]
    sentence = next((x.strip() for x in re.split(r"[\n.!?]", text) if re.search(r"\b" + re.escape(chosen) + r"\b", x, re.I) and len(x) > 30), None)
    if not sentence:
        return None
    id = hashlib.sha256((source["document_id"] + str(source["version"]) + str(source.get("revision", 1)) + str(source["slide"]) + sentence).encode()).hexdigest()[:32]
    options = words[:4]
    random.Random(id).shuffle(options)
    return {"id": id, "question": re.sub(r"\b" + re.escape(chosen) + r"\b", "_____", sentence, count=1, flags=re.I), "options": options,
            "source": source, "answer": chosen, "kind": "Comprensión del material aprobado"}


async def context(session, actor, id):
    visit = await own_visit(session, actor, id)
    saved = await session.get(VisitLearning, id)
    prior = await previous_report(session, visit)
    prior_learning = await session.get(VisitLearning, prior[0].id) if prior else None
    report = await session.get(VisitReport, id)
    current = report if report and report.status == "confirmed" else None
    source_visit, source_report = (visit, current) if current else (prior or (None, None))
    data = facts(source_report)
    entries = await catalogue(session, [visit.primary_line_id])
    site = await session.get(Institution, visit.institution_id) if visit.institution_id else None
    products, observations = [], []
    for p in data.products if data else []:
        products.append({"name": p.name, "objective": p.objective, "result": p.achievement, "evidence": p.evidence, "barriers": p.barriers})
        text = " ".join([p.evidence or "", *(p.barriers or [])])
        if re.search(r"estudio|evidencia|cient[ií]fic|publicaci[oó]n|art[ií]culo|comparativ", text, re.I):
            observations.append({"product": p.name, "text": text, "guidance": "Prepara la evidencia solicitada y revisa sus límites antes de presentarla.", "visit_id": str(source_visit.id)})
    names = {p["id"]:p["name"] for p in entries}
    goals = saved.data.get("objectives", []) if saved else []
    goal_query = " ".join(names.get(x["product_id"], "") + " " + x["objective"] for x in goals)
    prior_query = " ".join([p["name"] + " " + (p["evidence"] or "") for p in products])
    query = (goal_query[:300] + " " + prior_query[:200]).strip()
    sources = await retrieve(session, actor, query, visit.primary_line_id) if query else []
    lesson = next((q for q in (make_lesson(s) for s in sources) if q), None)
    answers = saved.data.get("answers", {}) if saved else {}
    lesson_out = {k: v for k, v in lesson.items() if k != "answer"} if lesson else None
    if lesson_out:
        lesson_out["attempt"] = answers.get(lesson["id"])
    return {"visit_id": str(id), "version": saved.version if saved else 0, "catalogue": entries,
            "objectives": saved.data.get("objectives", []) if saved else [], "site": {"name": site.name, "address": site.address} if site else None,
            "mode": "feedback" if current else "awaiting_report" if visit.finished_at else "preparation", "source_visit_id": str(source_visit.id) if source_visit else None,
            "source_at": source_visit.scheduled_at.isoformat() if source_visit else None,
            "products": products, "observations": observations, "sources": sources, "lesson": lesson_out,
            "learning_status": "available" if sources else "needs_approved_material",
            "previous_learning": prior_learning.data.get("answers", {}) if prior_learning else {},
            "reflection": saved.data.get("reflections", {}).get(lesson["id"]) if saved and lesson else None,
            "can_plan": actor.id == visit.representative_id and visit.status == "scheduled" and not visit.arrived_at and not visit.finished_at,
            "can_edit": actor.id == visit.representative_id}


async def command(session, actor, command):
    if command.type not in ("learning.plan", "learning.answer", "learning.reflection"):
        raise ApiError(422, "unknown_command", "Acción de preparación desconocida")
    schema = {"learning.plan":Plan, "learning.answer":Answer, "learning.reflection":Reflection}[command.type]
    payload = schema.model_validate(command.payload)
    visit = await own_visit(session, actor, payload.visit_id, write=True)
    row = await session.get(VisitLearning, visit.id)
    if command.expected_version != (row.version if row else 0):
        raise ApiError(409, "learning_changed", "Tu preparación cambió. Actualiza antes de guardar.")
    data = dict(row.data) if row else {}
    if command.type == "learning.plan":
        if visit.arrived_at or visit.finished_at or visit.status != "scheduled":
            raise ApiError(409, "preparation_closed", "La preparación terminó al iniciar la visita")
        entries = await catalogue(session, [visit.primary_line_id])
        allowed = {p["id"] for p in entries}
        if len({x.product_id for x in payload.objectives}) != len(payload.objectives) or any(str(x.product_id) not in allowed for x in payload.objectives):
            raise ApiError(422, "invalid_products", "Selecciona marcas diferentes del catálogo SNC")
        data["objectives"] = [x.model_dump(mode="json") for x in payload.objectives]
        from uno.modules.journey.service import locked_preparation, touch
        preparation = await locked_preparation(session, visit, clock.now())
        names = {p["id"]: p["name"] for p in entries}
        preparation.objective = "; ".join(names[str(x.product_id)] + ": " + x.objective + (". Medida: " + x.measure if x.measure else "") + (". Plazo: " + x.due if x.due else "") for x in payload.objectives) or None
        preparation.objective = preparation.objective[:500] if preparation.objective else None
        preparation.objective_edited = True
        await touch(session, visit, preparation, clock.now())
    else:
        current = await context(session, actor, visit.id)
        lesson = current.get("lesson")
        if not lesson or lesson["id"] != payload.lesson_id:
            raise ApiError(409, "lesson_changed", "El material cambió o no está aprobado. Vuelve a abrirlo.")
        if command.type == "learning.reflection":
            if len(payload.text.strip()) < 20:
                raise ApiError(422, "empty_reflection", "Escribe al menos 20 caracteres para conservar tu reflexión")
            reflections = dict(data.get("reflections", {}))
            reflections[lesson["id"]] = {"text":payload.text.strip(),"at":clock.now().isoformat(),"source":lesson["source"],"evaluated":False}
            data["reflections"] = reflections
        else:
            correct = make_lesson(lesson["source"])["answer"]
            if payload.answer not in lesson["options"]:
                raise ApiError(422, "invalid_answer", "Selecciona una de las opciones")
            answers = dict(data.get("answers", {}))
            before = answers.get(lesson["id"], {})
            answers[lesson["id"]] = {"correct": payload.answer == correct, "answer": payload.answer, "expected": correct,
                                     "attempts": before.get("attempts", 0) + 1, "at": clock.now().isoformat()}
            data["answers"] = answers
    if row is None:
        row = VisitLearning(visit_id=visit.id, data=data, version=1, updated_at=clock.now())
        session.add(row)
    else:
        row.data = data; row.version += 1; row.updated_at = clock.now()
    await session.flush()
    return {"version": row.version, "saved": True, "answers": data.get("answers", {})}
