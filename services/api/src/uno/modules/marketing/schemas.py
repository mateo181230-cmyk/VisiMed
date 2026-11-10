import uuid
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

KINDS = {
    "emergency": "Toma de urgencias",
    "training": "Capacitación",
    "roundtable": "Mesa de trabajo",
    "institutional": "Encuentro institucional",
    "other": "Otra actividad",
}
CONSULTATIONS = {
    "eps": "EPS",
    "prepaid": "Prepagada",
    "private": "Particular",
    "complementary": "Complementario",
    "institutional": "Institucional",
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Attendee(Strict):
    doctor_id: uuid.UUID | None = None
    name: str = Field(default="", max_length=160)
    specialty: str = Field(min_length=2, max_length=100)


class Material(Strict):
    name: str = Field(min_length=2, max_length=160)
    quantity: int = Field(ge=1, le=10000)


class ActivityInput(Strict):
    id: uuid.UUID
    representative_id: uuid.UUID
    line_id: uuid.UUID
    institution_id: uuid.UUID
    status: Literal["draft", "scheduled", "in_progress", "completed", "cancelled"]
    kind: Literal["emergency", "training", "roundtable", "institutional", "other"]
    objective: str = Field(min_length=5, max_length=2000)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    planned_attendees: int = Field(ge=1, le=1000)
    product_ids: list[uuid.UUID] = Field(min_length=1, max_length=30)
    consultation_types: list[
        Literal["eps", "prepaid", "private", "complementary", "institutional"]
    ] = Field(min_length=1, max_length=5)
    attendees: list[Attendee] = Field(default_factory=list, max_length=1000)
    materials: list[Material] = Field(default_factory=list, max_length=50)
    outcome: str = Field(default="", max_length=3000)
    next_action: str = Field(default="", max_length=1000)
    cancellation_reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def consistent(self):
        duration = (self.ends_at - self.starts_at).total_seconds()
        if duration < 300 or duration > 8 * 3600:
            raise ValueError("La actividad debe durar entre 5 minutos y 8 horas")
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("No repitas marcas")
        if self.status == "completed" and (not self.attendees or len(self.outcome) < 10):
            raise ValueError(
                "Para finalizar, relaciona los médicos asistentes y describe el resultado "
                "(10 caracteres como mínimo)"
            )
        if self.status == "cancelled" and len(self.cancellation_reason) < 10:
            raise ValueError("Explica el motivo de cancelación (10 caracteres como mínimo)")
        identities = []
        for attendee in self.attendees:
            if not attendee.doctor_id and len(attendee.name) < 5:
                raise ValueError("Escribe el nombre completo del médico fuera del panel")
            identities.append(
                str(attendee.doctor_id) if attendee.doctor_id else attendee.name.casefold()
            )
        if len(identities) != len(set(identities)):
            raise ValueError("Un médico solo puede aparecer una vez en la actividad")
        return self
