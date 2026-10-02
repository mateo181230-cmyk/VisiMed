"""Contenido del entrenamiento como código (doc 04 §5.3).

Todo lo que dice el médico, lo que se enseña y lo que se evalúa vive en ``content/``: escenarios,
lecturas, formularios, casting y banco de mensajes aprobados. Se valida al cargar; un contenido
inválido impide arrancar la API (mejor fallar temprano que mostrar un escenario roto).

La huella (``content_hash``) de un escenario cambia cuando cambia cualquier cosa que el médico
virtual recibe; ``training-apply`` publica una versión nueva solo si la huella cambió.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CONTENT_DIR = Path(__file__).with_name("content")
COMPETENCY_IDS = (
    "apertura",
    "sondeo",
    "parafraseo",
    "argumentacion",
    "manejo_objeciones",
    "cierre",
)
Difficulty = Literal["basico", "facil", "intermedio", "medio_alto", "alto"]
DIFFICULTY_LABEL = {
    "basico": "Básico",
    "facil": "Fácil",
    "intermedio": "Intermedio",
    "medio_alto": "Medio-alto",
    "alto": "Alto",
}


class Doctor(BaseModel):
    name: str
    gender: Literal["M", "F"]
    specialty: str
    years: int
    personality: str
    patients_per_day: str
    minutes: int = Field(ge=1, le=5)


class Barrier(BaseModel):
    code: str
    text: str


class LessonBlock(BaseModel):
    title: str
    text: str


class Lesson(BaseModel):
    title: str
    intro: str
    blocks: list[LessonBlock] = Field(min_length=3)
    example: str
    avoid: list[str]
    sources: list[str] = Field(min_length=1)


class QuizOption(BaseModel):
    id: str
    text: str
    correct: bool = False


class QuizQuestion(BaseModel):
    id: str
    skill: str
    question: str
    options: list[QuizOption] = Field(min_length=2)
    explanation: str
    source: str = Field(min_length=3)

    @model_validator(mode="after")
    def _one_correct(self) -> QuizQuestion:
        if sum(o.correct for o in self.options) != 1:
            raise ValueError(f"La pregunta {self.id} debe tener exactamente una respuesta correcta")
        if len({o.id for o in self.options}) != len(self.options):
            raise ValueError(f"La pregunta {self.id} repite ids de opción")
        return self

    @property
    def correct_option(self) -> str:
        return next(o.id for o in self.options if o.correct)


class Approval(BaseModel):
    min_total: int = Field(ge=0, le=30)
    min_competencies: dict[str, int] = {}
    blocking_errors: list[str] = []

    @model_validator(mode="after")
    def _known(self) -> Approval:
        unknown = set(self.min_competencies) - set(COMPETENCY_IDS)
        if unknown:
            raise ValueError(f"Competencias desconocidas en la aprobación: {sorted(unknown)}")
        return self


class Casting(BaseModel):
    face_id: str
    face_name: str
    voice_id: str
    voice_name: str
    tts_model: str = "eleven_turbo_v2_5"


class Flow(BaseModel):
    turn_taking_patience: Literal["low", "medium", "high"]
    pal_interruptibility: Literal["low", "medium", "high"]
    idle_engagement: Literal["off", "patient", "eager"]


class Challenge(BaseModel):
    """La resistencia se define por escenario; no se hereda del médico más exigente."""

    max_objections: int = Field(ge=0, le=3)
    requires_evidence: bool
    pressure_questions: list[str]
    time_rules: list[str] = Field(min_length=1)
    success_criterion: str


class Scenario(BaseModel):
    slug: str
    order: int
    product: str
    segment: str
    title: str
    skill: str
    promise: str
    instruction: str
    difficulty: Difficulty
    doctor: Doctor
    current_molecule: str
    opening_level: str
    barrier: Barrier
    objective: str
    main_argument: str
    secondary_argument: str
    base_objection: str
    objections: list[str] = Field(min_length=1)
    greetings: list[str] = Field(min_length=1)
    expected_close: str
    bot_behavior: list[str] = Field(min_length=1)
    challenge: Challenge
    lesson: Lesson
    quiz: list[QuizQuestion] = Field(min_length=2)
    approval: Approval
    casting: Casting
    flow: Flow
    sources: list[str] = Field(min_length=1)

    @property
    def difficulty_label(self) -> str:
        return DIFFICULTY_LABEL[self.difficulty]

    def greeting(self, index: int, salutation: str) -> str:
        """Saludo aprobado número ``index`` (rota entre intentos) con el trato del visitador."""
        text = self.greetings[index % len(self.greetings)]
        return text.replace("{trato}", salutation)


class BankMessage(BaseModel):
    id: str
    area: str
    text: str = Field(min_length=10)
    source: str = Field(min_length=3)  # todo mensaje aprobado dice de dónde sale
    trigger: str | None = None
    prefer_for: list[str] = []


class Bank(BaseModel):
    messages: list[BankMessage]

    def best_for(self, area: str, scenario: Scenario) -> BankMessage | None:
        """Mensaje aprobado para reforzar ``area``: primero el pensado para este escenario."""
        candidates = [m for m in self.messages if m.area == area]
        preferred = [m for m in candidates if scenario.slug in m.prefer_for]
        pool = preferred or candidates
        return pool[0] if pool else None


class Common(BaseModel):
    product: dict[str, str]
    guardrails: list[str]
    reactions: list[str]
    time_rules: list[str]
    pressure_questions: list[str]
    success_criterion: str
    tavus: dict[str, object]
    consent: dict[str, str]


class Catalog(BaseModel):
    common: Common
    bank: Bank
    scenarios: list[Scenario]

    def get(self, slug: str) -> Scenario | None:
        return next((s for s in self.scenarios if s.slug == slug), None)

    def content_hash(self, scenario: Scenario) -> str:
        """Huella de todo lo que recibe el médico virtual de este escenario."""
        blob = json.dumps(
            {"scenario": scenario.model_dump(), "common": self.common.model_dump()},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(blob.encode()).hexdigest()


def load_catalog(directory: Path = CONTENT_DIR) -> Catalog:
    common = Common.model_validate_json((directory / "common.json").read_text(encoding="utf-8"))
    bank = Bank.model_validate_json((directory / "bank.json").read_text(encoding="utf-8"))
    scenarios = [
        Scenario.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted((directory / "scenarios").glob("*.json"))
    ]
    scenarios.sort(key=lambda s: s.order)
    slugs = [s.slug for s in scenarios]
    if len(set(slugs)) != len(slugs):
        raise ValueError("Hay escenarios con el mismo slug")
    for scenario in scenarios:
        for area in scenario.approval.min_competencies:
            if bank.best_for(area, scenario) is None:
                raise ValueError(f"El banco no tiene mensajes para «{area}»")
    return Catalog(common=common, bank=bank, scenarios=scenarios)


@lru_cache
def get_catalog() -> Catalog:
    return load_catalog()
