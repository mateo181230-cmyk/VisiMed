"""El plazo del resumen empieza con el aviso, nunca con la llegada ni con «Terminé»."""

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from uno.db import next_change_seq
from uno.modules.agenda.models import Visit
from uno.modules.calls.models import VisitReport

REPORT_WINDOW = timedelta(minutes=30)


async def notify_report(session: AsyncSession, visit: Visit, now: datetime) -> None:
    if visit.report_notified_at is not None:
        return
    report = await session.get(VisitReport, visit.id)
    if report is not None and report.status == "confirmed":
        return
    visit.report_notified_at = now
    visit.report_due_at = now + REPORT_WINDOW
    visit.updated_at = now
    visit.change_seq = await next_change_seq(session)


def report_expired(visit: Visit, at: datetime) -> bool:
    return visit.report_invalid_at is not None or (
        visit.report_due_at is not None and at >= visit.report_due_at
    )


async def invalidate_report(session: AsyncSession, visit: Visit, now: datetime) -> None:
    # Compatibility name: the 30-minute target now marks a pending report,
    # never invalidates evidence or prevents written completion.
    if visit.report_pending_at is None:
        visit.report_pending_at = visit.report_due_at or now
        visit.report_invalid_at = None
        visit.updated_at = now
        visit.change_seq = await next_change_seq(session)
