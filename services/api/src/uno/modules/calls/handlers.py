"""Eventos del visitador sobre su ficha: confirmarla y corregir un campo (doc 02 T6.1, T6.2).

- ``report_confirmed``: el visitador da por buena la ficha (un toque). Idempotente.
- ``report_field_edited``: corrige un campo. Lo que escribe el visitador queda con
  ``source = "rep_edit"`` y **nunca** lo pisa una nueva extracción de la llamada.

El visitador puede corregir los datos de la conversación y la fecha de seguimiento. La fecha
derivada se actualiza junto con la fecha explícita; los metadatos de llegada/salida conservan
su propia trazabilidad.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uno import events
from uno.db import next_change_seq
from uno.modules.agenda.models import Visit
from uno.modules.calls.deadlines import invalidate_report
from uno.modules.calls.models import Call, CallVisit, VisitReport
from uno.modules.calls.products import refresh_discussed_lines
from uno.modules.calls.schema import coerce_value, missing_report_fields
from uno.modules.sync.registry import EventContext, Rejected, handles

EDITABLE_FIELDS = (
    "snc_report_json",
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
    "visit_objective",
    "discussion",
    "doctor_interest",
    "doctor_disinterest",
    "doctor_reaction",
    "new_information",
    "receptiveness_score",
    "free_note",
    "products_discussed",
    "current_preference",
    "receptiveness",
    "samples_delivered",
    "next_action_date",
    "doctor_commitment",
    "representative_commitment",
    "previous_commitment_fulfilled",
    "objective_progress",
    "commitment_quantity",
    "commitment_due_date",
    "next_visit_objective",
    "location_change_reason",
)


class ReportConfirmedPayload(BaseModel):
    pass


class SNCReportSubmittedPayload(BaseModel):
    value: str = Field(max_length=24000)
    confirm: bool = False
    expected_version: int = Field(ge=0)


@handles("snc_report_submitted", SNCReportSubmittedPayload)
async def snc_report_submitted(ctx: EventContext, p: SNCReportSubmittedPayload) -> None:
    # One sync event = one transaction. An invalid edit cannot confirm an older report.
    _, report = await _own_report(ctx, create=True)
    if report.change_seq != p.expected_version and p.expected_version != 0:
        raise Rejected("report_changed_reload")
    if p.expected_version == 0 and report.fields:
        raise Rejected("report_changed_reload")
    await report_field_edited(ctx, ReportFieldEditedPayload(field="snc_report_json", value=p.value))
    if p.confirm:
        await report_confirmed(ctx, ReportConfirmedPayload())


class ReportFieldEditedPayload(BaseModel):
    field: Literal[
        "snc_report_json",
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
        "visit_objective",
        "discussion",
        "doctor_interest",
        "doctor_disinterest",
        "doctor_reaction",
        "new_information",
        "receptiveness_score",
        "free_note",
        "products_discussed",
        "current_preference",
        "receptiveness",
        "samples_delivered",
        "next_action_date",
        "doctor_commitment",
        "representative_commitment",
        "previous_commitment_fulfilled",
        "objective_progress",
        "commitment_quantity",
        "commitment_due_date",
        "next_visit_objective",
        "location_change_reason",
    ]
    # ``null`` o texto vacío borra el campo.
    value: str | int | bool | None = Field(default=None)


async def _own_report(ctx: EventContext, *, create: bool = False) -> tuple[Visit, VisitReport]:
    if ctx.visit_id is None:
        raise Rejected("visit_id_required")
    visit = await ctx.session.get(Visit, ctx.visit_id)
    if visit is None or visit.representative_id != ctx.user.id:
        raise Rejected("unknown_visit")
    report = await ctx.session.get(VisitReport, visit.id)
    if report is None:
        if not create or visit.status not in (
            "finished",
            "in_call",
            "processing",
            "ready",
            "no_interview",
            "error",
        ):
            raise Rejected("no_report")
        report = VisitReport(
            visit_id=visit.id,
            fields={},
            created_at=ctx.now,
            updated_at=ctx.now,
            extractor_version="rep-written-v1",
            change_seq=await next_change_seq(ctx.session),
        )
        ctx.session.add(report)
        await ctx.session.flush()
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
    if not any(e.get("value") not in (None, "", False) for e in (report.fields or {}).values()):
        raise Rejected("empty_report")
    raw = (report.fields or {}).get("snc_report_json", {}).get("value")
    if raw:
        from uno.modules.calls.snc_report import SNCReport
        facts = SNCReport.model_validate_json(raw)
        if not (facts.products or facts.not_attended_reason or facts.commitments or facts.referrals):
            raise Rejected("empty_report")
    from uno.modules.calls.brands import review_report
    _, brand_issues = await review_report(ctx.session, visit, report)
    if brand_issues:
        raise Rejected("brand_review_required")
    # The target remains measurable; late confirmation preserves all evidence.
    visit.report_invalid_at = None
    report.complete = not missing_report_fields(report.fields or {})
    report.status = "confirmed"
    report.confirmed_at = ctx.now
    from uno.modules.workflows.tasks import reconcile_tasks
    await reconcile_tasks(ctx.session, visit, report, ctx.now)
    await _touch(ctx.session, report, ctx)
    if visit.status in ("ready", "processing", "in_call", "finished"):
        visit.status = "confirmed"
        visit.updated_at = ctx.now
        visit.change_seq = await next_change_seq(ctx.session)
    for _cv, call in (
        await ctx.session.execute(
            select(CallVisit, Call)
            .join(Call, Call.id == CallVisit.call_id)
            .where(
                CallVisit.visit_id == visit.id,
                CallVisit.live.is_(True),
                Call.status == "queued",
            )
        )
    ).all():
        call.status = "cancelled"
        call.updated_at = ctx.now
        links = await ctx.session.scalars(select(CallVisit).where(CallVisit.call_id == call.id))
        for link in links:
            link.live = False
    edited = sum(1 for e in (report.fields or {}).values() if e.get("source") == "rep_edit")
    await events.emit(
        ctx.session,
        event_type="report_confirmed",
        occurred_at=ctx.occurred_at,
        recorded_at=ctx.now,
        actor_type="representative",
        actor_id=ctx.user.id,
        entities=_entities(visit),
        payload={"edited_fields": edited, "complete": report.complete,
                 "late": bool(visit.report_due_at and ctx.occurred_at >= visit.report_due_at)},
        correlation_id=visit.id,
        causation_id=ctx.event_id,
    )


@handles("report_field_edited", ReportFieldEditedPayload)
async def report_field_edited(ctx: EventContext, p: ReportFieldEditedPayload) -> None:
    visit, report = await _own_report(ctx, create=True)
    try:
        value = coerce_value(p.field, p.value)
    except ValueError:
        raise Rejected("invalid_value") from None

    if p.field == "snc_report_json" and value:
        from uno.modules.calls.brands import catalogue, review
        value, brand_issues = review(value, await catalogue(ctx.session, [visit.primary_line_id]))
        if report.status == "confirmed" and brand_issues:
            raise Rejected("brand_review_required")
    fields = dict(report.fields or {})
    current = fields.get(p.field)
    entry = {"value": value, "confidence": "high", "source": "rep_edit"}
    if current == entry:
        return  # el mismo cambio otra vez
    fields[p.field] = entry
    if p.field == "snc_report_json" and value:
        from uno.modules.calls.snc_report import SNCReport, legacy_projection
        data = SNCReport.model_validate_json(value)
        if report.status == "confirmed" and not (
            data.products or data.not_attended_reason or data.commitments or data.referrals
        ):
            raise Rejected("empty_report")
        projection = legacy_projection(data)
        for name, text in projection.items():
            fields[name] = {"value": coerce_value(name, text or None), "confidence":"high", "source":"rep_edit"}
    elif p.field == "snc_report_json" and report.status == "confirmed":
        raise Rejected("empty_report")
    if report.status != "confirmed":
        visit.report_mode = "written"
        visit.updated_at = ctx.now
        visit.change_seq = await next_change_seq(ctx.session)
        if visit.status in ("finished", "in_call", "processing"):
            visit.status = "ready"
        if visit.report_due_at and ctx.occurred_at >= visit.report_due_at:
            await invalidate_report(ctx.session, visit, ctx.now)
    if p.field == "next_action_date":
        fields["next_action_due"] = dict(entry)
        fields["next_action_in_days"] = {"value": None, "confidence": "high", "source": "rep_edit"}
    if p.field == "order_taken":
        if value is True:
            fields["no_order_reason"] = {
                "value": "not_applicable",
                "confidence": "high",
                "source": "rep_edit",
            }
        elif fields.get("no_order_reason", {}).get("value") == "not_applicable":
            fields["no_order_reason"] = {"value": None, "confidence": "high", "source": "rep_edit"}
    report.fields = fields
    if report.status == "confirmed" and p.field == "snc_report_json":
        from uno.modules.workflows.tasks import reconcile_tasks
        await reconcile_tasks(ctx.session, visit, report, ctx.now)
    # reasignar: SQLAlchemy no detecta cambios dentro de un JSON
    report.complete = not missing_report_fields(fields)
    from uno.modules.calls.brands import review_report
    await review_report(ctx.session, visit, report)
    if p.field in ("products_discussed", "snc_report_json"):
        await refresh_discussed_lines(ctx.session, visit.id, fields)
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
