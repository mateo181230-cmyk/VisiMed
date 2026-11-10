"""Public journey contract. Missing evidence stays null, never a generated fact."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class PreparationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str | None = Field(default=None, max_length=500)
    rep_commitment: str | None = Field(default=None, max_length=500)

    @field_validator("objective", "rep_commitment")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ActivityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    started_at: AwareDatetime
    ended_at: AwareDatetime
    seconds: int = Field(ge=1, le=60, strict=True)

    @model_validator(mode="after")
    def valid_interval(self) -> ActivityPayload:
        length = (self.ended_at - self.started_at).total_seconds()
        if length <= 0 or length > 65 or self.seconds > length + 1:
            raise ValueError("El intervalo debe contener el tiempo activo y durar hasta un minuto")
        return self


class ActivityIn(ActivityPayload):
    event_id: uuid.UUID


class QuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    question: str = Field(min_length=1, max_length=1000)

    @field_validator("question")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Escribe tu pregunta")
        return value


class ContextOut(BaseModel):
    source_visit_id: uuid.UUID | None = None
    source_at: datetime | None = None
    summary: str | None = None
    doctor_interest: str | None = None
    barrier: str | None = None
    current_preference: str | None = None
    doctor_commitment: str | None = None
    opening_question: str
    recommended_message: str


class TranscriptTurnOut(BaseModel):
    role: Literal["agent", "user"]
    text: str


class TranscriptOut(BaseModel):
    status: Literal["available", "missing", "shared_call"]
    turns: list[TranscriptTurnOut]


class PreparationMetricsOut(BaseModel):
    active_seconds: int
    prepared_at: datetime | None
    prepared_recorded_at: datetime | None
    question_count: int


class MessageOut(BaseModel):
    request_id: uuid.UUID
    question: str
    answer: str
    created_at: datetime


class AIAvailabilityOut(BaseModel):
    available: bool
    mode: str


class PreparationOut(BaseModel):
    pending_tasks: list[dict] = []
    visit_id: uuid.UUID
    objective: str | None
    rep_commitment: str | None
    context: ContextOut
    brief: str
    previous_transcript: TranscriptOut
    metrics: PreparationMetricsOut
    messages: list[MessageOut]
    ai: AIAvailabilityOut


class FeedbackCriterionOut(BaseModel):
    key: str
    label: str
    value: str | int | None
    evidence_field: str


class FeedbackOut(BaseModel):
    visit_id: uuid.UUID
    score: int | None
    max_score: int = 10
    band: str
    why: str
    provisional: bool = True
    rubric_version: str
    rubric_description: str
    report_status: str | None
    report_updated_at: datetime | None
    summary: str | None
    new_information: str | None
    barrier: str | None
    competitor: str | None
    doctor_commitment: str | None
    rep_commitment_fulfilled: str | None
    commitment_quantity: int | None
    commitment_due_date: str | None
    next_objective: str
    advice: str
    criteria: list[FeedbackCriterionOut]


class ManagerVisitOut(BaseModel):
    visit_id: uuid.UUID
    representative_id: uuid.UUID
    representative_name: str
    doctor_id: uuid.UUID
    doctor_name: str
    scheduled_at: datetime
    status: str
    active_seconds: int
    prepared_at: datetime | None
    prepared_recorded_at: datetime | None
    question_count: int
    score: int | None
    report_status: str | None
    rep_commitment_fulfilled: str | None


class ManagerMetricsOut(BaseModel):
    since: datetime
    until: datetime
    visits: list[ManagerVisitOut]
    rubric_version: str
