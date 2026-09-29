"""Eventos del visitador sobre su ficha: confirmarla y corregir un campo (doc 02 T6.1, T6.2).

- ``report_confirmed``: el visitador da por buena la ficha (un toque). Idempotente.
- ``report_field_edited``: corrige un campo. Lo que escribe el visitador queda con
  ``source = "rep_edit"`` y **nunca** lo pisa una nueva extracción de la llamada.

Solo se pueden corregir los campos que el visitador entiende y necesita; los derivados (fecha de la
próxima acción, disposición, muestras…) se muestran pero no se editan.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from uno import events
from uno.db import next_change_seq
from uno.modules.agenda.models import Visit
from uno.modules.calls.models import VisitReport
from uno.modules.calls.schema import coerce_value
from uno.modules.sync.registry import EventContext, Rejected, handles

EDITABLE_FIELDS = (
    "interest_level",
    "visit_outcome",
    "order_taken",
    "no_order_reason",
    "objection",
    "competitor",
    "commitment",
    "next_action",
    "territory_signal",
    "summary",
)


class ReportConfirmedPayload(BaseModel):
    pass


class ReportFieldEditedPayload(BaseModel):
    field: Literal[
        "interest_level",
        "visit_outcome",
        "order_taken",
        "no_order_reason",
        "objection",
        "competitor",
        "commitment",
        "next_action",
        "territory_signal",
        "summary",
    ]
    # ``null`` o texto vacío borra el campo.
    value: str | int | bool | None = Field(default=None)


async def _own_report(ctx: EventContext) -> tuple[Visit, VisitReport]:
    if ctx.visit_id is None:
        raise Rejected("visit_id_required")
    visit = await ctx.session.get(Visit, ctx.visit_id)
    if visit is None or visit.representative_id != ctx.user.id:
        raise Rejected("unknown_visit")
    report = await ctx.session.get(VisitReport, visit.id)
    if report is None:
        raise Rejected("no_report")
    return visit, report


def _entities(visit: Visit) -> dict[str, Any]:
    return {
        "visit_id": visit.id,
        "doctor_id": visit.doctor_id,
        "institution_id": visit.institution_id,
        "representative_id": visit.representative_id,
        "product_line_ids": [visit.primary_line_id],
    }


async def _touch(session: AsyncSession, report: VisitReport, ctx: EventContext) -> None:
    report.updated_at = ctx.now
    report.change_seq = await next_change_seq(session)


@handles("report_confirmed", ReportConfirmedPayload)
async def report_confirmed(ctx: EventContext, p: ReportConfirmedPayload) -> None:
    visit, report = await _own_report(ctx)
    if report.status == "confirmed":
        return  # reenviar es seguro
    report.status = "confirmed"
    report.confirmed_at = ctx.now
    await _touch(ctx.session, report, ctx)
    if visit.status in ("ready", "processing", "in_call", "finished"):
        visit.status = "confirmed"
        visit.updated_at = ctx.now
        visit.change_seq = await next_change_seq(ctx.session)
    edited = sum(1 for e in (report.fields or {}).values() if e.get("source") == "rep_edit")
    await events.emit(
        ctx.session,
        event_type="report_confirmed",
        occurred_at=ctx.occurred_at,
        recorded_at=ctx.now,
        actor_type="representative",
        actor_id=ctx.user.id,
        entities=_entities(visit),
        payload={"edited_fields": edited, "complete": report.complete},
        correlation_id=visit.id,
        causation_id=ctx.event_id,
    )


@handles("report_field_edited", ReportFieldEditedPayload)
async def report_field_edited(ctx: EventContext, p: ReportFieldEditedPayload) -> None:
    visit, report = await _own_report(ctx)
    try:
        value = coerce_value(p.field, p.value)
    except ValueError:
        raise Rejected("invalid_value") from None

    fields = dict(report.fields or {})
    current = fields.get(p.field)
    entry = {"value": value, "confidence": "high", "source": "rep_edit"}
    if current == entry:
        return  # el mismo cambio otra vez
    fields[p.field] = entry
    report.fields = fields  # reasignar: SQLAlchemy no detecta cambios dentro de un JSON
    await _touch(ctx.session, report, ctx)
    await events.emit(
        ctx.session,
        event_type="report_edited",
        occurred_at=ctx.occurred_at,
        recorded_at=ctx.now,
        actor_type="representative",
        actor_id=ctx.user.id,
        entities=_entities(visit),
        # Nunca el valor: es texto libre y puede llevar datos personales.
        payload={
            "field": p.field,
            "cleared": value is None,
            "was_confirmed": report.status == "confirmed",
        },
        correlation_id=visit.id,
        causation_id=ctx.event_id,
    )
