"""Operación de las llamadas desde la terminal: ver, correr un ciclo y probar de punta a punta.

``run_test_call`` prepara visitas de prueba ya terminadas para un celular y deja que el
orquestador real las llame, así se prueba el mismo camino que usará el visitador (eventos
idempotentes → orquestador → proveedor → ficha) y no un atajo.
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from uno import clock
from uno.context import AppContext
from uno.ids import uuid7
from uno.modules.agenda.models import Visit
from uno.modules.auth import service as auth_service
from uno.modules.auth.models import User
from uno.modules.calls import service
from uno.modules.calls.models import Call, CallVisit, VisitReport
from uno.modules.catalog.models import Doctor, ProductLine
from uno.modules.sync.service import IncomingEvent, process_batch
from uno.security import normalize_phone

LABELS = {
    "interest_level": "Interés (1–5)",
    "visit_outcome": "Resultado",
    "order_taken": "¿Hubo pedido?",
    "no_order_reason": "Si no, ¿por qué?",
    "receptiveness": "Disposición",
    "objection": "Objeción",
    "competitor": "Competencia",
    "current_preference": "Usa hoy",
    "commitment": "Compromiso",
    "next_action": "Próximo paso",
    "next_action_in_days": "En (días)",
    "next_action_due": "Fecha",
    "samples_delivered": "¿Muestras?",
    "products_discussed": "Productos",
    "territory_signal": "Señal del territorio",
    "summary": "Resumen",
}
TEST_DOCTORS = [
    ("Dra. Ana de Prueba", "Medicina Interna"),
    ("Dr. Luis de Prueba", "Gastroenterología"),
    ("Dra. Marta de Prueba", "Medicina General"),
]
TEST_INSTITUTION = "Clínica de Prueba UNO"


def _short(value: uuid.UUID | None) -> str:
    return str(value)[:8] if value else "—"


def describe_fields(fields: dict[str, Any]) -> list[str]:
    lines = []
    for name, label in LABELS.items():
        entry = fields.get(name)
        if not entry:
            continue
        mark = " (dudosa)" if entry.get("confidence") == "low" else ""
        origin = " ✎" if entry.get("source") == "rep_edit" else ""
        lines.append(f"    {label:24} {entry['value']}{mark}{origin}")
    return lines


async def list_calls(ctx: AppContext, limit: int = 20) -> list[str]:
    async with ctx.sessionmaker() as session:
        rows = (
            await session.execute(
                select(Call, User.full_name)
                .join(User, User.id == Call.representative_id)
                .order_by(Call.created_at.desc())
                .limit(limit)
            )
        ).all()
        lines = []
        for call, rep_name in rows:
            visits = (
                await session.execute(select(CallVisit).where(CallVisit.call_id == call.id))
            ).scalars().all()
            when = call.scheduled_for.astimezone(clock.tz("America/Bogota")).strftime("%d/%m %H:%M")
            lines.append(
                f"{_short(call.id)}  {call.status:10} intento {call.attempt}  {when}  "
                f"{len(visits)} visita(s)  {rep_name}"
                + (f"  [{call.failure_reason}]" if call.failure_reason else "")
                + ("  (cierre)" if call.is_closing else "")
            )
        return lines


async def show_call(ctx: AppContext, prefix: str) -> list[str]:
    async with ctx.sessionmaker() as session:
        calls = (
            (await session.execute(select(Call).order_by(Call.created_at.desc()).limit(200)))
            .scalars()
            .all()
        )
        matches = [c for c in calls if str(c.id).startswith(prefix)]
        if len(matches) != 1:
            return [f"Hay {len(matches)} llamadas que empiezan por «{prefix}»"]
        call = matches[0]
        out = [
            f"Llamada {call.id}",
            f"  estado {call.status} · intento {call.attempt} · duración {call.duration_s or '—'} s"
            f" · conversación {call.provider_conversation_id or '—'}",
        ]
        if call.summary:
            out.append(f"  resumen del proveedor: {call.summary}")
        pairs = (
            await session.execute(
                select(CallVisit, Visit, Doctor)
                .join(Visit, Visit.id == CallVisit.visit_id)
                .join(Doctor, Doctor.id == Visit.doctor_id)
                .where(CallVisit.call_id == call.id)
                .order_by(CallVisit.position)
            )
        ).all()
        for cv, visit, doctor in pairs:
            out.append(f"\n  Visita {cv.position}: {doctor.full_name} · estado {visit.status}")
            report = await session.get(VisitReport, visit.id)
            if report:
                out.append(f"    ficha {report.status} · completa: {report.complete}")
                out += describe_fields(report.fields)
        if call.transcript:
            out.append("\n  Transcripción:")
            for turn in call.transcript:
                who = "UNO" if turn["role"] == "agent" else "VISITADOR"
                out.append(f"    {who:9}: {turn['text']}")
        return out


async def _ensure_test_rep(ctx: AppContext, phone: str) -> User:
    async with ctx.sessionmaker() as session:
        user = (
            await session.execute(select(User).where(User.phone_e164 == phone))
        ).scalar_one_or_none()
        if user is not None:
            return user
        user = await auth_service.create_user(
            session,
            ctx.settings,
            full_name="Visitador de Prueba",
            phone=phone,
            pin="".join(secrets.choice("0123456789") for _ in range(6)),
            role="rep",
            now=clock.now(),
        )
        await session.commit()
        return user


async def prepare_test_visits(ctx: AppContext, rep: User, count: int) -> list[uuid.UUID]:
    """Deja ``count`` visitas de prueba recién terminadas, por el mismo camino que el teléfono."""
    from uno.seed import seed_lines

    await seed_lines(ctx)
    now = clock.now()
    async with ctx.sessionmaker() as session:
        line = (
            await session.execute(select(ProductLine).where(ProductLine.code == "GASTRU"))
        ).scalar_one()
    inst_id = uuid.uuid5(uuid.NAMESPACE_URL, f"uno-test-institution:{TEST_INSTITUTION}")
    events: list[IncomingEvent] = []
    visit_ids: list[uuid.UUID] = []
    for n in range(count):
        name, specialty = TEST_DOCTORS[n % len(TEST_DOCTORS)]
        doctor_id = uuid.uuid5(uuid.NAMESPACE_URL, f"uno-test-doctor:{rep.id}:{name}")
        visit_id = uuid7()
        start = now - timedelta(minutes=25 * (count - n) + 10)
        finish = start + timedelta(minutes=12)
        common = {"app_version": "call-test"}
        events += [
            IncomingEvent(
                event_id=uuid7(),
                type="doctor_created",
                visit_id=None,
                device_ts=start - timedelta(hours=1),
                payload={
                    "doctor_id": str(doctor_id),
                    "full_name": name,
                    "specialty": specialty,
                    "default_line_id": str(line.id),
                    "institution": {"id": str(inst_id), "name": TEST_INSTITUTION, "city": "Bogotá"},
                },
                **common,
            ),
            IncomingEvent(
                event_id=uuid7(),
                type="visit_scheduled",
                visit_id=visit_id,
                device_ts=start - timedelta(minutes=30),
                payload={
                    "doctor_id": str(doctor_id),
                    "line_ids": [str(line.id)],
                    "scheduled_at": start.isoformat(),
                },
                **common,
            ),
            IncomingEvent(
                event_id=uuid7(),
                type="visit_arrived",
                visit_id=visit_id,
                device_ts=start,
                payload={"location": None, "permission": "granted"},
                **common,
            ),
            IncomingEvent(
                event_id=uuid7(),
                type="visit_finished",
                visit_id=visit_id,
                device_ts=finish,
                payload={"location": None, "permission": "granted"},
                **common,
            ),
        ]
        visit_ids.append(visit_id)
    await process_batch(
        ctx.sessionmaker,
        user=rep,
        device_id=uuid.uuid5(uuid.NAMESPACE_URL, "uno-test-device"),
        events=events,
        sent_at=now,
        now=now,
    )
    return visit_ids


async def run_test_call(
    ctx: AppContext,
    phone: str,
    visits: int,
    *,
    timeout_minutes: int,
    ignore_window: bool,
    say: Callable[[str], None],
    as_rep: str | None = None,
) -> bool:
    """Prepara visitas de prueba, deja que el orquestador llame y muestra lo que salió.

    ``phone`` es el celular que va a sonar. Con ``as_rep`` las visitas de prueba son de esa cuenta
    de la app (por ejemplo la de demostración) y el resumen aparece en su Historial.
    """
    s = ctx.settings
    phone = normalize_phone(phone)
    if s.call_backend == "off" or ctx.voice_provider is None:
        say("Las llamadas están apagadas (UNO_CALL_BACKEND=off). Usa fake o elevenlabs.")
        return False
    rep_phone = normalize_phone(as_rep) if as_rep else phone
    if as_rep:
        s.call_phone_override = phone  # suena tu celular; el resultado queda en la cuenta indicada
    if s.call_backend == "elevenlabs" and s.dial_phone(rep_phone) not in s.allowed_call_phones:
        say(
            f"{phone} no está en UNO_CALL_ALLOWED_PHONES: por seguridad, en pruebas solo se "
            "llama a celulares autorizados. Agrégalo a ~/.uno-visitas/secrets.env y "
            "vuelve a correr."
        )
        return False

    s.call_batch_wait_seconds = 0
    if ignore_window:
        s.call_window_start_hour, s.call_window_end_hour = 0, 24
    rep = await _ensure_test_rep(ctx, rep_phone)
    local = clock.now().astimezone(clock.tz(rep.timezone))
    if not s.call_window_start_hour <= local.hour < s.call_window_end_hour:
        say(
            f"Ahora son las {local:%H:%M} en {rep.timezone}: fuera del horario de llamadas "
            f"({s.call_window_start_hour}:00–{s.call_window_end_hour}:00). Usa --ignore-window."
        )
        return False

    visit_ids = await prepare_test_visits(ctx, rep, visits)
    say(f"Preparé {visits} visita(s) de prueba terminadas para {phone}. Llamando…")
    deadline = clock.now() + timedelta(minutes=timeout_minutes)
    last = ""
    while clock.now() < deadline:
        await service.run_call_cycle(ctx, clock.now())
        async with ctx.sessionmaker() as session:
            call = (
                await session.execute(
                    select(Call)
                    .join(CallVisit, CallVisit.call_id == Call.id)
                    .where(CallVisit.visit_id == visit_ids[0])
                    .order_by(Call.created_at.desc())
                )
            ).scalars().first()
        if call is not None:
            state = f"{call.status} (intento {call.attempt})" + (
                f" · {call.failure_reason}" if call.failure_reason else ""
            )
            if state != last:
                say(f"  llamada: {state}")
                last = state
            if call.status in ("completed", "failed", "cancelled"):
                for line in await show_call(ctx, str(call.id)[:12]):
                    say(line)
                return call.status == "completed"
        await asyncio.sleep(2)
    say("Se acabó el tiempo de espera sin resultado.")
    return False
