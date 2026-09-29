"""Datos iniciales y de demostración.

- ``seed_lines``: las tres líneas del piloto (RESPI, OSTRU, GASTRU). Es un dato de producción.
- ``seed_demo``: usuarios y agenda **ficticios** para probar en local. Las credenciales de prueba
  viven aquí y solo aquí (no en el README ni en el chat del equipo). No usar en producción.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from uno import clock
from uno.context import AppContext
from uno.db import next_change_seq
from uno.ids import uuid7
from uno.modules.auth.models import User
from uno.modules.auth.service import create_user
from uno.modules.catalog.models import Institution, ProductLine
from uno.modules.notifications import service as notif_service
from uno.modules.sync.service import IncomingEvent, process_batch

LINES = [("RESPI", "RESPI"), ("OSTRU", "OSTRU"), ("GASTRU", "GASTRU")]

DEMO_ADMIN = {"name": "Admin Demo", "phone": "+573000000001", "pin": "246810", "role": "admin"}
DEMO_REP = {"name": "Visitador Demo", "phone": "+573000000002", "pin": "135790", "role": "rep"}

DEMO_DOCTORS = [
    ("Dr. Carlos Gómez", "Medicina General", "Hospital San Rafael", "GASTRU"),
    ("Dra. Laura Méndez", "Medicina Interna", "Clínica Central", "GASTRU"),
    ("Dr. Andrés Torres", "Gastroenterología", "Hospital del Valle", "GASTRU"),
    ("Dra. Patricia Ruiz", "Medicina General", "Clínica Moderna", "RESPI"),
]

# Referencia de geocerca de dos instituciones demo. Son instituciones y puntos **ficticios**
# (coordenadas genéricas de Bogotá, no las de un hospital real); las otras dos quedan sin
# referencia a propósito, para probar el estado «sin_referencia».
DEMO_INSTITUTION_RADIUS_M = 300
DEMO_INSTITUTION_REFS = {
    "Hospital San Rafael": (4.6533, -74.0836),
    "Hospital del Valle": (4.7110, -74.0721),
}


async def seed_lines(ctx: AppContext) -> int:
    """Crea las líneas que falten. Devuelve cuántas creó."""
    created = 0
    async with ctx.sessionmaker() as session:
        existing = {c for (c,) in (await session.execute(select(ProductLine.code))).all()}
        for code, name in LINES:
            if code in existing:
                continue
            session.add(
                ProductLine(
                    id=uuid7(), code=code, name=name, change_seq=await next_change_seq(session)
                )
            )
            created += 1
        await session.commit()
    return created


async def _ensure_user(ctx: AppContext, spec: dict[str, str], now: datetime) -> User:
    async with ctx.sessionmaker() as session:
        found = (
            await session.execute(select(User).where(User.phone_e164 == spec["phone"]))
        ).scalar_one_or_none()
        if found is not None:
            return found
        user = await create_user(
            session,
            ctx.settings,
            full_name=spec["name"],
            phone=spec["phone"],
            pin=spec["pin"],
            role=spec["role"],
            now=now,
        )
        await session.commit()
        return user


async def seed_demo(ctx: AppContext) -> dict[str, str]:
    """Usuarios de demostración, un panel de 4 médicos y visitas para hoy y mañana."""
    now = clock.now()
    await seed_lines(ctx)
    admin = await _ensure_user(ctx, DEMO_ADMIN, now)
    rep = await _ensure_user(ctx, DEMO_REP, now)

    async with ctx.sessionmaker() as session:
        lines = {r.code: r.id for r in (await session.execute(select(ProductLine))).scalars()}
        await notif_service.get_prefs(session, rep.id, now)
        await session.commit()

    # Se pasan por el mismo camino que usa el teléfono (eventos idempotentes). Las visitas se
    # agendan relativas a la hora actual (en múltiplos de 5 min) para poder probar «Siguiente»,
    # «Después» y los recordatorios sin depender de la hora del día.
    zone = clock.tz(rep.timezone)
    minute = (now.minute // 5) * 5
    base = now.replace(minute=minute, second=0, microsecond=0)
    offsets = [
        timedelta(minutes=45),
        timedelta(hours=2),
        timedelta(hours=3, minutes=30),
        timedelta(hours=5),
    ]
    events: list[IncomingEvent] = []
    doctor_ids: list[uuid.UUID] = []
    for (name, specialty, institution, line_code), offset in zip(
        DEMO_DOCTORS, offsets, strict=True
    ):
        doctor_id = uuid.uuid5(uuid.NAMESPACE_URL, f"uno-demo-doctor:{name}")
        inst_id = uuid.uuid5(uuid.NAMESPACE_URL, f"uno-demo-institution:{institution}")
        doctor_ids.append(doctor_id)
        events.append(
            IncomingEvent(
                event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"uno-demo-ev-doctor:{name}"),
                type="doctor_created",
                visit_id=None,
                device_ts=now - timedelta(minutes=5),
                app_version="seed",
                payload={
                    "doctor_id": str(doctor_id),
                    "full_name": name,
                    "specialty": specialty,
                    "default_line_id": str(lines[line_code]),
                    "institution": {"id": str(inst_id), "name": institution, "city": "Bogotá"},
                },
            )
        )
        start = base + offset
        day = start.astimezone(zone).date()
        visit_id = uuid.uuid5(uuid.NAMESPACE_URL, f"uno-demo-visit:{name}:{day}")
        events.append(
            IncomingEvent(
                event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"uno-demo-ev-visit:{name}:{day}"),
                type="visit_scheduled",
                visit_id=visit_id,
                device_ts=now - timedelta(minutes=4),
                app_version="seed",
                payload={
                    "doctor_id": str(doctor_id),
                    "line_ids": [str(lines[line_code])],
                    "scheduled_at": start.isoformat(),
                },
            )
        )
    await process_batch(
        ctx.sessionmaker,
        user=rep,
        device_id=uuid.uuid5(uuid.NAMESPACE_URL, "uno-demo-device"),
        events=events,
        sent_at=now,
        now=now,
    )
    await _seed_institution_refs(ctx)
    return {"admin": admin.phone_e164, "rep": rep.phone_e164}


async def _seed_institution_refs(ctx: AppContext) -> None:
    """Pone la referencia de geocerca a las instituciones demo que aún no tienen una.

    No pisa una referencia ya fijada (por ejemplo con ``set-institution-ref``). Sube
    ``change_seq`` para que el teléfono la baje.
    """
    async with ctx.sessionmaker() as session:
        for name, (lat, lng) in DEMO_INSTITUTION_REFS.items():
            inst_id = uuid.uuid5(uuid.NAMESPACE_URL, f"uno-demo-institution:{name}")
            inst = await session.get(Institution, inst_id)
            if inst is None or inst.lat is not None or inst.lng is not None:
                continue
            inst.lat = lat
            inst.lng = lng
            inst.radius_m = DEMO_INSTITUTION_RADIUS_M
            inst.ref_source = "manual"
            inst.change_seq = await next_change_seq(session)
        await session.commit()
