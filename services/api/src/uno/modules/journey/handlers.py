"""Offline preparation uses the same domain services and the sync event's occurrence time."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from uno.errors import ApiError
from uno.modules.agenda.models import Visit
from uno.modules.journey import service
from uno.modules.journey.schema import ActivityPayload, PreparationPatch
from uno.modules.sync.registry import EventContext, Rejected, handles


async def own_visit(ctx: EventContext) -> Visit:
    if ctx.visit_id is None:
        raise Rejected("visit_id_required")
    try:
        return await service.own_visit(ctx.session, ctx.user, ctx.visit_id)
    except ApiError:
        raise Rejected("unknown_visit") from None


@handles("visit_preparation_updated", PreparationPatch)
async def preparation_updated(ctx: EventContext, payload: PreparationPatch) -> None:
    visit = await own_visit(ctx)
    try:
        await service.update_preparation(
            ctx.session, visit, payload, occurred_at=ctx.occurred_at, now=ctx.now
        )
    except ApiError as error:
        raise Rejected(error.code) from None


@handles("visit_preparation_activity", ActivityPayload)
async def preparation_activity(ctx: EventContext, payload: ActivityPayload) -> None:
    visit = await own_visit(ctx)
    try:
        await service.record_activity(
            ctx.session, visit, payload, event_id=ctx.event_id, now=ctx.now
        )
    except ApiError as error:
        raise Rejected(error.code) from None


class PreparedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


@handles("visit_prepared", PreparedPayload)
async def visit_prepared(ctx: EventContext, payload: PreparedPayload) -> None:
    visit = await own_visit(ctx)
    try:
        await service.mark_prepared(ctx.session, visit, occurred_at=ctx.occurred_at, now=ctx.now)
    except ApiError as error:
        raise Rejected(error.code) from None
