"""Envío de notificaciones y detección de las que ya toca enviar.

Tipos automáticos:

- ``visit_reminder``: ``remind_before_min`` minutos antes de cada visita agendada.
- ``daily_digest``: resumen de la agenda del día a la hora local elegida (ventana de 4 h).
- ``preparation_reminder``: agenda de mañana a las 18:30 locales por defecto (ventana de 2 h).

Cada envío se **reclama** insertando una fila en ``notification_log`` con restricción única
(usuario, tipo, referencia, canal): dos trabajadores a la vez, o el mismo trabajador dos veces,
nunca envían dos veces. Un envío fallido se reintenta hasta 3 veces con espera creciente.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.context import AppContext
from uno.ids import uuid7
from uno.modules.agenda.models import Visit
from uno.modules.auth.models import User
from uno.modules.catalog.models import Doctor, Institution
from uno.modules.notifications import messages
from uno.modules.notifications.models import (
    NotificationLog,
    NotificationPreference,
    PushSubscription,
)
from uno.modules.notifications.senders import EmailError, PushMessage, PushTarget

log = logging.getLogger("uno.notifications")

MAX_ATTEMPTS = 3
LEASE = timedelta(minutes=10)  # tiempo máximo que un envío «en curso» se considera vivo
DIGEST_WINDOW = timedelta(hours=4)
PREPARATION_WINDOW = timedelta(hours=2)
BACKOFF = {1: timedelta(minutes=2), 2: timedelta(minutes=10)}


@dataclass(frozen=True)
class Notice:
    kind: str  # visit_reminder | daily_digest | preparation_reminder | test
    ref: str  # identifica el hecho notificado (para no repetirlo)
    title: str
    body: str
    url: str = "/"
    tag: str | None = None


# --------------------------------------------------------------------- reclamar y enviar


async def _claim(
    session: AsyncSession, user_id: uuid.UUID, notice: Notice, channel: str, now: datetime
) -> uuid.UUID | None:
    """Devuelve el id de la fila reclamada, o ``None`` si otro ya lo envió o lo tiene en curso."""
    row = NotificationLog(
        id=uuid7(),
        user_id=user_id,
        kind=notice.kind,
        ref=notice.ref,
        channel=channel,
        status="pending",
        attempts=1,
        next_attempt_at=now + LEASE,
        created_at=now,
    )
    session.add(row)
    try:
        await session.commit()
        return row.id
    except IntegrityError:
        await session.rollback()

    existing = (
        await session.execute(
            select(NotificationLog).where(
                NotificationLog.user_id == user_id,
                NotificationLog.kind == notice.kind,
                NotificationLog.ref == notice.ref,
                NotificationLog.channel == channel,
            )
        )
    ).scalar_one_or_none()
    if existing is None or existing.attempts >= MAX_ATTEMPTS:
        return None
    retryable = existing.status in ("failed", "pending") and (
        existing.next_attempt_at is not None and existing.next_attempt_at <= now
    )
    if not retryable:
        return None
    # Comparar y cambiar de forma atómica: solo uno gana el reintento.
    result = await session.execute(
        update(NotificationLog)
        .where(
            NotificationLog.id == existing.id,
            NotificationLog.status == existing.status,
            NotificationLog.attempts == existing.attempts,
        )
        .values(status="pending", attempts=existing.attempts + 1, next_attempt_at=now + LEASE)
    )
    await session.commit()
    return existing.id if result.rowcount == 1 else None  # type: ignore[attr-defined]


async def _finish(
    session: AsyncSession,
    log_id: uuid.UUID,
    *,
    status: str,
    now: datetime,
    error: str | None = None,
) -> None:
    row = await session.get(NotificationLog, log_id)
    if row is None:
        return
    row.status = status
    row.error = (error or "")[:200] or None
    if status == "sent":
        row.sent_at = now
        row.next_attempt_at = None
    elif status == "failed":
        row.next_attempt_at = now + BACKOFF.get(row.attempts, timedelta(hours=1))
    else:
        row.next_attempt_at = None
    await session.commit()


async def deliver(
    ctx: AppContext,
    user_id: uuid.UUID,
    notice: Notice,
    now: datetime,
    *,
    channels: tuple[str, ...] = ("push", "email"),
    force: bool = False,
) -> dict[str, str]:
    """Envía ``notice`` por los canales pedidos que el usuario tenga activos.

    ``force`` ignora los interruptores del usuario (solo el botón «Enviar prueba»); igual se
    exige una suscripción o un correo verificado.
    Devuelve ``{canal: estado}`` con estado ``sent | failed | skipped | duplicate``.
    """
    out: dict[str, str] = {}
    async with ctx.sessionmaker() as session:
        prefs = await session.get(NotificationPreference, user_id)
    if prefs is None:
        return out

    if "push" in channels and (prefs.push_enabled or force):
        out["push"] = await _deliver_push(ctx, user_id, notice, now)
    if "email" in channels and (prefs.email_enabled or force):
        out["email"] = await _deliver_email(ctx, user_id, prefs, notice, now)
    return out


async def _deliver_push(ctx: AppContext, user_id: uuid.UUID, notice: Notice, now: datetime) -> str:
    async with ctx.sessionmaker() as session:
        # Se copian a datos simples: reclamar puede hacer rollback y expirar los objetos ORM.
        targets = [
            (row.id, PushTarget(row.endpoint, row.p256dh, row.auth))
            for row in (
                await session.execute(
                    select(PushSubscription).where(
                        PushSubscription.user_id == user_id, PushSubscription.disabled_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        ]
        if not targets:
            return "skipped"
        log_id = await _claim(session, user_id, notice, "push", now)
        if log_id is None:
            return "duplicate"

        message = PushMessage(
            title=notice.title, body=notice.body, url=notice.url, tag=notice.tag, kind=notice.kind
        )
        any_ok = False
        last_error: str | None = None
        for sub_id, target in targets:
            result = await ctx.push_sender.send(target, message)
            if result.ok:
                any_ok = True
                await session.execute(
                    update(PushSubscription)
                    .where(PushSubscription.id == sub_id)
                    .values(last_success_at=now, failed_count=0)
                )
            else:
                last_error = result.error
                values: dict[str, object] = {"failed_count": PushSubscription.failed_count + 1}
                if result.gone:
                    values["disabled_at"] = now  # el navegador la dio de baja
                await session.execute(
                    update(PushSubscription).where(PushSubscription.id == sub_id).values(**values)
                )
        await session.commit()
        await _finish(
            session,
            log_id,
            status="sent" if any_ok else "failed",
            now=now,
            error=None if any_ok else last_error,
        )
        return "sent" if any_ok else "failed"


async def _deliver_email(
    ctx: AppContext,
    user_id: uuid.UUID,
    prefs: NotificationPreference,
    notice: Notice,
    now: datetime,
) -> str:
    if not prefs.email or prefs.email_verified_at is None:
        return "skipped"
    async with ctx.sessionmaker() as session:
        log_id = await _claim(session, user_id, notice, "email", now)
        if log_id is None:
            return "duplicate"
        try:
            await ctx.email_sender.send(
                messages.to_email(prefs.email, notice.title, notice.body, ctx.settings.app_base_url)
            )
        except EmailError as exc:
            await _finish(session, log_id, status="failed", now=now, error=str(exc))
            return "failed"
        await _finish(session, log_id, status="sent", now=now)
        return "sent"


# --------------------------------------------------------------------- qué toca enviar


async def run_due_reminders(ctx: AppContext, now: datetime | None = None) -> dict[str, int]:
    """Recorre a los usuarios con notificaciones activas y envía lo que ya toca.

    Es seguro llamarla cuantas veces se quiera (cada minuto desde el trabajador): la
    restricción única de ``notification_log`` evita duplicados.
    """
    now = now or clock.now()
    stats: dict[str, int] = defaultdict(int)
    async with ctx.sessionmaker() as session:
        rows = (
            await session.execute(
                select(NotificationPreference, User)
                .join(User, User.id == NotificationPreference.user_id)
                .where(
                    User.is_active.is_(True),
                    or_(
                        NotificationPreference.push_enabled.is_(True),
                        NotificationPreference.email_enabled.is_(True),
                    ),
                )
            )
        ).all()

    for prefs, user in rows:
        try:
            await _visit_reminders(ctx, prefs, user, now, stats)
            await _daily_digest(ctx, prefs, user, now, stats)
            await _preparation_reminder(ctx, prefs, user, now, stats)
        except Exception:
            log.exception("falló el envío de avisos de un usuario")
            stats["errors"] += 1
    return dict(stats)


def _count(stats: dict[str, int], result: dict[str, str], kind: str) -> None:
    for channel, status in result.items():
        stats[f"{kind}.{channel}.{status}"] += 1


async def _visit_reminders(
    ctx: AppContext,
    prefs: NotificationPreference,
    user: User,
    now: datetime,
    stats: dict[str, int],
) -> None:
    if prefs.remind_before_min <= 0:
        return
    horizon = now + timedelta(minutes=prefs.remind_before_min)
    async with ctx.sessionmaker() as session:
        rows = (
            await session.execute(
                select(Visit, Doctor.full_name, Institution.name)
                .join(Doctor, Doctor.id == Visit.doctor_id)
                .outerjoin(Institution, Institution.id == Visit.institution_id)
                .where(
                    Visit.representative_id == user.id,
                    Visit.status == "scheduled",
                    Visit.scheduled_at > now,
                    Visit.scheduled_at <= horizon,
                )
                .order_by(Visit.scheduled_at)
            )
        ).all()
    zone = clock.tz(user.timezone)
    for visit, doctor_name, institution_name in rows:
        local = visit.scheduled_at.astimezone(zone)
        minutes = max(1, round((visit.scheduled_at - now).total_seconds() / 60))
        title, body = messages.visit_reminder(
            local_time=local,
            minutes_before=min(minutes, prefs.remind_before_min),
            doctor_name=doctor_name,
            institution=institution_name,
            include_names=ctx.settings.notify_include_names,
        )
        notice = Notice(
            kind="visit_reminder",
            # La referencia incluye la hora: si la visita se reprograma, se avisa de nuevo.
            ref=f"{visit.id}:{int(visit.scheduled_at.timestamp()) // 60}",
            title=title,
            body=body,
            url="/",
            tag=f"visit-{visit.id}",
        )
        result = await deliver(ctx, user.id, notice, now)
        _count(stats, result, "visit_reminder")


async def _daily_digest(
    ctx: AppContext,
    prefs: NotificationPreference,
    user: User,
    now: datetime,
    stats: dict[str, int],
) -> None:
    if not prefs.digest_enabled:
        return
    zone = clock.tz(user.timezone)
    local_now = now.astimezone(zone)
    hh, mm = (int(x) for x in prefs.digest_time.split(":"))
    start = datetime.combine(local_now.date(), time(hh, mm), tzinfo=zone)
    if not (start <= local_now < start + DIGEST_WINDOW):
        return
    day_start, day_end = clock.local_day_bounds(local_now.date(), user.timezone)
    async with ctx.sessionmaker() as session:
        rows = (
            await session.execute(
                select(Visit, Doctor.full_name, Institution.name)
                .join(Doctor, Doctor.id == Visit.doctor_id)
                .outerjoin(Institution, Institution.id == Visit.institution_id)
                .where(
                    Visit.representative_id == user.id,
                    Visit.status != "not_done",
                    Visit.scheduled_at >= day_start,
                    Visit.scheduled_at < day_end,
                )
                .order_by(Visit.scheduled_at)
            )
        ).all()
    if not rows:
        return
    first, doctor_name, institution_name = rows[0]
    title, body = messages.daily_digest(
        local_day=local_now,
        count=len(rows),
        first_time=first.scheduled_at.astimezone(zone),
        first_doctor=doctor_name,
        first_institution=institution_name,
        include_names=ctx.settings.notify_include_names,
    )
    notice = Notice(
        kind="daily_digest",
        ref=local_now.date().isoformat(),
        title=title,
        body=body,
        url="/",
        tag="daily-digest",
    )
    result = await deliver(ctx, user.id, notice, now)
    _count(stats, result, "daily_digest")


async def _preparation_reminder(
    ctx: AppContext,
    prefs: NotificationPreference,
    user: User,
    now: datetime,
    stats: dict[str, int],
) -> None:
    if not prefs.preparation_enabled or not prefs.push_enabled:
        return
    zone = clock.tz(user.timezone)
    local_now = now.astimezone(zone)
    hh, mm = (int(value) for value in prefs.preparation_time.split(":"))
    start = datetime.combine(local_now.date(), time(hh, mm), tzinfo=zone)
    if not (start <= local_now < start + PREPARATION_WINDOW):
        return
    tomorrow = local_now.date() + timedelta(days=1)
    day_start, day_end = clock.local_day_bounds(tomorrow, user.timezone)
    async with ctx.sessionmaker() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Visit)
            .where(
                Visit.representative_id == user.id,
                Visit.status == "scheduled",
                Visit.scheduled_at >= day_start,
                Visit.scheduled_at < day_end,
            )
        )
    if not count:
        return
    title, body = messages.preparation_reminder(count=count)
    notice = Notice(
        kind="preparation_reminder",
        ref=tomorrow.isoformat(),
        title=title,
        body=body,
        url=f"/preparacion?fecha={tomorrow.isoformat()}",
        tag=f"preparation-{tomorrow.isoformat()}",
    )
    result = await deliver(ctx, user.id, notice, now, channels=("push",))
    _count(stats, result, "preparation_reminder")
