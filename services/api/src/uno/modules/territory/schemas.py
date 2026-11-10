from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Command(Strict):
    id: uuid.UUID
    type: str = Field(max_length=50)
    expected_version: int = Field(default=0, ge=0)
    payload: dict


class Point(Strict):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class VerifyLocation(Point):
    institution_id: uuid.UUID
    source: Literal["map", "gps", "geocoder"]
    confirmed: Literal[True]
    accuracy_m: float | None = Field(default=None, gt=0, le=1000)
    note: str = Field(default="", max_length=600)


class Opening(Strict):
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(min_length=1, max_length=7)
    opens: time = time(8)
    closes: time = time(17)

    @model_validator(mode="after")
    def valid_hours(self):
        if self.opens >= self.closes or len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("Revisa los días y el horario de recepción")
        return self


class ConsultationMix(Strict):
    eps: int = Field(default=0, ge=0)
    private: int = Field(default=0, ge=0)
    prepaid: int = Field(default=0, ge=0)
    complementary: int = Field(default=0, ge=0)
    unknown: int = Field(default=0, ge=0)


class AvailabilityInput(Strict):
    doctor_id: uuid.UUID
    institution_id: uuid.UUID
    reception: Opening
    additional_reception: list[Opening] = Field(default_factory=list, max_length=6)
    appointment_required: bool = False
    source: Literal["doctor", "representative", "document"]
    observed_on: date
    notes: str = Field(default="", max_length=1000)


class PotentialInput(Strict):
    doctor_id: uuid.UUID
    institution_id: uuid.UUID
    practice_days: list[Annotated[int, Field(ge=0, le=6)]] = Field(min_length=1, max_length=7)
    patients_per_day: int = Field(ge=0, le=1000)
    consultations: ConsultationMix
    reception: Opening | None = None
    appointment_required: bool = False
    appointment_notice_days: int = Field(default=0, ge=0, le=90)
    snc_percentage: float | None = Field(default=None, ge=0, le=100)
    source: Literal["doctor", "representative", "document"]
    observed_on: date
    notes: str = Field(default="", max_length=1500)

    @model_validator(mode="after")
    def valid_mix(self):
        if sum(self.consultations.model_dump().values()) != self.patients_per_day:
            raise ValueError(
                "Las modalidades, incluyendo desconocidas, deben sumar pacientes por día"
            )
        if len(set(self.practice_days)) != len(self.practice_days):
            raise ValueError("No repitas días de atención")
        return self


class PharmacyInput(Strict):
    id: uuid.UUID
    representative_id: uuid.UUID | None = None
    name: str = Field(min_length=2, max_length=160)
    chain: str = Field(default="Independiente", min_length=1, max_length=160)
    address: str = Field(min_length=5, max_length=200)
    city: str = Field(default="Bogotá", min_length=2, max_length=80)
    contact: str = Field(default="", max_length=160)
    phone: str = Field(default="", max_length=30)
    reception: Opening
    additional_reception: list[Opening] = Field(default_factory=list, max_length=6)
    active: bool = True


class SchedulePharmacy(Strict):
    id: uuid.UUID
    pharmacy_id: uuid.UUID
    scheduled_at: datetime

    @model_validator(mode="after")
    def timezone(self):
        if self.scheduled_at.tzinfo is None:
            raise ValueError("Incluye zona horaria")
        return self


class VisitAction(Strict):
    id: uuid.UUID
    occurred_at: datetime
    point: Point | None = None
    accuracy_m: float | None = Field(default=None, gt=0, le=10000)
    reason: str = Field(default="", max_length=600)

    @model_validator(mode="after")
    def timezone(self):
        if self.occurred_at.tzinfo is None:
            raise ValueError("Incluye zona horaria")
        if self.point and self.accuracy_m is None:
            raise ValueError("Incluye la precisión de la ubicación")
        return self


class StockObservation(Strict):
    product_id: uuid.UUID
    stock: float | None = Field(default=None, ge=0, le=1000000)
    unit: str = Field(min_length=1, max_length=40)
    rotation: float | None = Field(default=None, ge=0, le=1000000)
    period_days: int | None = Field(default=None, ge=1, le=366)
    source: Literal["observed", "declared"]

    @model_validator(mode="after")
    def period(self):
        if self.rotation is not None and self.period_days is None:
            raise ValueError("La rotación requiere un periodo")
        return self


class CommercialAction(Strict):
    product_id: uuid.UUID
    kind: Literal["suggested_order", "requested_order", "confirmed_transfer"]
    quantity: float = Field(gt=0, le=1000000)
    unit: str = Field(min_length=1, max_length=40)
    value_cop: float | None = Field(default=None, ge=0, le=100000000000)
    evidence: str = Field(default="", max_length=600)

    @model_validator(mode="after")
    def confirmation(self):
        if self.kind == "confirmed_transfer" and not self.evidence.strip():
            raise ValueError("Una transferencia confirmada necesita soporte o referencia")
        return self


class FollowUp(Strict):
    action: str = Field(min_length=3, max_length=600)
    due_on: date
    owner: Literal["representative", "commercial"] = "representative"


class PharmacyReport(Strict):
    id: uuid.UUID
    observations: list[StockObservation] = Field(default_factory=list, max_length=50)
    commercial: list[CommercialAction] = Field(default_factory=list, max_length=50)
    action: str = Field(min_length=3, max_length=1500)
    result: Literal["achieved", "partial", "not_achieved", "unknown"]
    barriers: str = Field(default="", max_length=1500)
    followups: list[FollowUp] = Field(default_factory=list, max_length=20)
    confirmed: Literal[True]


class ReferralInput(Strict):
    id: uuid.UUID
    visit_id: uuid.UUID
    pharmacy_id: uuid.UUID
    product_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=1000)


class PolicyInput(Strict):
    representative_id: uuid.UUID
    active: bool = False
    publish_automatically: bool = True
    origin: Point
    origin_label: str = Field(min_length=2, max_length=160)
    return_to_origin: bool = False
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4], min_length=1, max_length=7
    )
    starts: time = time(8)
    ends: time = time(17)
    lunch_starts: time = time(12)
    lunch_ends: time = time(13)
    travel_mode: Literal["car"] = "car"
    medical_minutes: int = Field(default=20, ge=5, le=180)
    pharmacy_minutes: int = Field(default=20, ge=5, le=180)
    max_contacts: Literal[12] = 12
    excluded_dates: list[date] = Field(default_factory=list, max_length=366)
    allow_unconfirmed_reception: bool = False
    starts_on: date | None = None
    ends_on: date | None = None

    @model_validator(mode="after")
    def times(self):
        if self.starts_on and self.ends_on and self.starts_on > self.ends_on:
            raise ValueError("El fin del piloto debe ser posterior a su inicio")
        if not self.starts < self.lunch_starts < self.lunch_ends < self.ends:
            raise ValueError("Revisa jornada y almuerzo: deben estar ordenados sin superponerse")
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("No repitas días de trabajo")
        return self


class CycleWindow(Strict):
    start: date
    end: date

    @model_validator(mode="after")
    def order(self):
        if self.start > self.end:
            raise ValueError("La ventana termina antes de iniciar")
        return self


class RequirementInput(Strict):
    id: uuid.UUID
    representative_id: uuid.UUID
    doctor_id: uuid.UUID | None = None
    institution_id: uuid.UUID | None = None
    pharmacy_id: uuid.UUID | None = None
    cycle_start: date
    cycle_end: date
    windows: list[CycleWindow] = Field(min_length=1, max_length=20)
    min_gap_days: int = Field(default=6, ge=1, le=90)
    product_sequence: list[uuid.UUID] = Field(default_factory=list, max_length=5)
    service_minutes: int = Field(default=20, ge=5, le=180)
    priority: int = Field(default=1, ge=1, le=5)
    active: bool = True

    @model_validator(mode="after")
    def windows_valid(self):
        if bool(self.doctor_id) == bool(self.pharmacy_id):
            raise ValueError("Selecciona un médico o una droguería")
        if self.cycle_end < self.cycle_start or (self.cycle_end - self.cycle_start).days > 90:
            raise ValueError("El ciclo debe durar entre 1 y 91 días")
        last = None
        for window in self.windows:
            if window.start < self.cycle_start or window.end > self.cycle_end:
                raise ValueError("Las ventanas deben estar dentro del ciclo")
            if last is not None and window.start <= last:
                raise ValueError(
                    "Las ventanas de frecuencia deben ser consecutivas y no superponerse"
                )
            last = window.end
        if len(set(self.product_sequence)) != len(self.product_sequence):
            raise ValueError("No repitas productos en la secuencia")
        return self


class GenerateInput(Strict):
    representative_id: uuid.UUID
    day: date
    max_contacts: int = Field(default=12, ge=1, le=20)


class PublishInput(Strict):
    id: uuid.UUID
    reason: str = Field(default="", max_length=1000)
