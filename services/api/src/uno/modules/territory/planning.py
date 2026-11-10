from __future__ import annotations

import asyncio
import unicodedata
import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.db import next_change_seq
from uno.errors import ApiError
from uno.events import DomainEvent, emit
from uno.ids import uuid7
from uno.modules.agenda.models import Visit, VisitLine
from uno.modules.auth.models import User
from uno.modules.catalog.models import Doctor, Institution, Panel

from .models import (
    LocationVerification,
    MedicalPotential,
    Pharmacy,
    PharmacyVisit,
    ReceptionAvailability,
    RouteJob,
    RoutePlan,
    RoutePolicy,
    VisitRequirement,
)
from .optimizer import optimize
from .providers import bogota_point, cache_key, driving_matrix
from .service import ZONE, enqueue, potential_summary


def minute(value):
    value = time.fromisoformat(value) if isinstance(value, str) else value
    return value.hour * 60 + value.minute


def instant(day, minutes):
    return (datetime.combine(day, time(0), tzinfo=ZONE) + timedelta(minutes=minutes)).astimezone(
        UTC
    )


def in_bogota(value):
    normalized = "".join(
        c for c in unicodedata.normalize("NFD", value or "") if unicodedata.category(c) != "Mn"
    ).upper()
    return normalized.startswith("BOGOTA")


def working_day(data, day):
    if data.get("starts_on") and day < date.fromisoformat(data["starts_on"]):
        return False
    if data.get("ends_on") and day > date.fromisoformat(data["ends_on"]):
        return False
    return day.weekday() in data["weekdays"] and day.isoformat() not in data.get(
        "excluded_dates", []
    )


def next_working_day(data, day):
    for offset in range(1, 370):
        candidate = day + timedelta(days=offset)
        if data.get("ends_on") and candidate > date.fromisoformat(data["ends_on"]):
            return candidate  # sentinel, filtered by working_day at the call site
        if working_day(data, candidate):
            return candidate
    raise ApiError(422, "no_working_day", "Revisa los días de trabajo y las fechas excluidas")


def execution_point(visit, kind, site):
    """Use a reliable field reading for the next leg, never overwrite the site."""
    if kind == "doctor":
        readings = [
            (visit.finish_lat, visit.finish_lng, visit.finish_precision_m),
            (visit.arrival_lat, visit.arrival_lng, visit.arrival_precision_m),
        ]
    else:
        readings = []
        for moment in ("finish", "arrive"):
            reading = (visit.location or {}).get(moment, {})
            point = reading.get("point") or {}
            readings.append((point.get("lat"), point.get("lng"), reading.get("accuracy_m")))
    for lat, lng, accuracy in readings:
        if (
            lat is not None
            and lng is not None
            and accuracy is not None
            and accuracy <= 100
            and bogota_point(lat, lng)
        ):
            return lat, lng
    return (site.lat, site.lng) if site else (None, None)


def event_days(event, data, today):
    """A moved appointment changes both dates, not just the day it was edited."""
    days = {today, next_working_day(data, today)}
    for key in ("scheduled_at", "previous_scheduled_at"):
        value = event.payload.get(key)
        if value:
            try:
                day = datetime.fromisoformat(value).astimezone(ZONE).date()
                if today <= day <= today + timedelta(days=90):
                    days.add(day)
            except (TypeError, ValueError):
                pass
    return sorted(days)


async def inputs(session: AsyncSession, rep: uuid.UUID, day: date):
    policy = await session.get(RoutePolicy, rep)
    if not policy:
        raise ApiError(422, "missing_policy", "Falta configurar la jornada y su punto de inicio")
    data = policy.data
    if not working_day(data, day):
        raise ApiError(422, "non_working_day", "La fecha no es un día laboral de esta política")
    rules = (
        (
            await session.execute(
                select(VisitRequirement).where(
                    VisitRequirement.representative_id == rep,
                    VisitRequirement.active.is_(True),
                    VisitRequirement.cycle_start <= day,
                    VisitRequirement.cycle_end >= day,
                )
            )
        )
        .scalars()
        .all()
    )
    medical = (
        (
            await session.execute(
                select(Visit).where(
                    Visit.representative_id == rep,
                    Visit.scheduled_at >= instant(day - timedelta(days=100), 0),
                    Visit.scheduled_at < instant(day + timedelta(days=91), 0),
                )
            )
        )
        .scalars()
        .all()
    )
    channel = (
        (
            await session.execute(
                select(PharmacyVisit).where(
                    PharmacyVisit.representative_id == rep,
                    PharmacyVisit.scheduled_at >= instant(day - timedelta(days=100), 0),
                    PharmacyVisit.scheduled_at < instant(day + timedelta(days=91), 0),
                )
            )
        )
        .scalars()
        .all()
    )
    candidates = []
    issues = []
    locked = []
    fingerprints = [policy.version, policy.data, [[str(r.id), r.version] for r in rules]]
    seen = set()
    start = minute(data["starts"])
    origin = dict(data["origin"])
    today = clock.now().astimezone(ZONE).date()
    if day == today:
        start = max(start, minute(clock.now().astimezone(ZONE)) + 2)

    from uno.modules.workflows.models import RouteIncident

    incidents = (
        await session.scalars(
            select(RouteIncident).where(
                RouteIncident.representative_id == rep, RouteIncident.day == day
            )
        )
    ).all()
    for incident in incidents:
        fingerprints.append(
            [str(incident.id), incident.resume_at.isoformat() if incident.resume_at else None]
        )
        if incident.resume_at:
            start = max(start, minute(incident.resume_at.astimezone(ZONE)))

    def issue(key, reason, label="", code="review"):
        issues.append({"key": key, "reason": reason, "label": label, "code": code})

    async def candidate(kind, target_id, rule=None, visit=None):
        doc = await session.get(Doctor, target_id) if kind == "doctor" else None
        requested_site = (
            visit.institution_id if visit is not None and kind == "doctor" else None
        ) or (rule.institution_id if rule else None)
        if not requested_site and doc:
            requested_site = doc.institution_id
        key = f"{kind}:{target_id}" + (f":{requested_site}" if requested_site else "")
        fixed = visit is not None and visit.planned_by != "routing"
        if key in seen:
            if fixed:
                issue(
                    key,
                    "Hay varias citas del mismo destino; revisa la agenda antes de publicar",
                    code="fixed_conflict",
                )
            return
        seen.add(key)
        pharmacy = await session.get(Pharmacy, target_id) if kind == "pharmacy" else None
        site_id = requested_site or (
            doc.institution_id if doc else pharmacy.institution_id if pharmacy else None
        )
        site = await session.get(Institution, site_id) if site_id else None
        label = doc.full_name if doc else (site.name if site else "Droguería")
        geo = await session.get(LocationVerification, site.id) if site else None
        potential = await session.get(MedicalPotential, (doc.id, site.id)) if doc and site else None
        availability = (
            await session.get(ReceptionAvailability, (doc.id, site.id)) if doc and site else None
        )
        panel = await session.get(Panel, (rep, doc.id)) if doc else None
        fingerprints.append(
            [
                key,
                rule.version if rule else None,
                geo.version if geo else None,
                potential.version if potential else None,
                availability.version if availability else None,
                pharmacy.version if pharmacy else None,
            ]
        )
        if not site or not geo or geo.status != "verified" or site.lat is None or site.lng is None:
            issue(
                key,
                "Falta verificar la ubicación de la sede",
                label,
                "fixed_location" if fixed else "location",
            )
            return
        if not in_bogota(site.city) or not bogota_point(site.lat, site.lng):
            issue(
                key,
                "La sede no pertenece al alcance Bogotá",
                label,
                "fixed_scope" if fixed else "scope",
            )
            return
        if kind == "doctor" and (not panel or not panel.default_line_id):
            issue(
                key,
                "Falta la línea del médico en el panel",
                label,
                "fixed_line" if fixed else "line",
            )
            return
        if pharmacy and not pharmacy.active:
            issue(key, "Droguería inactiva", label, "fixed_inactive" if fixed else "inactive")
            return
        service = (
            rule.data["service_minutes"]
            if rule
            else data["medical_minutes" if doc else "pharmacy_minutes"]
        )
        provisional = False
        reception_windows = []
        if fixed:
            arrival = minute(visit.scheduled_at.astimezone(ZONE))
            opens = arrival
            closes = arrival + service
            if arrival < start:
                issue(
                    key,
                    "Cita vencida: requiere reprogramación explícita",
                    label,
                    "missed_appointment",
                )
                return
        else:
            reception = (
                availability.data["reception"]
                if availability
                else potential.data.get("reception")
                if potential
                else pharmacy.data.get("reception")
                if pharmacy
                else None
            )
            if not reception:
                if data.get("allow_unconfirmed_reception", False):
                    provisional = True
                    reception = {
                        "weekdays": data["weekdays"],
                        "opens": data["starts"],
                        "closes": data["ends"],
                    }
                    issue(
                        key,
                        "Horario por confirmar: propuesta dentro de la jornada del visitador",
                        label,
                        "provisional_availability",
                    )
                else:
                    issue(key, "Falta el horario de recepción del médico", label, "availability")
                    return
            receptions = [reception] + (
                availability.data.get("additional_reception", [])
                if availability
                else pharmacy.data.get("additional_reception", [])
                if pharmacy
                else []
            )
            reception_windows = [
                [minute(r["opens"]), minute(r["closes"])]
                for r in receptions
                if day.weekday() in r["weekdays"]
            ]
            if not reception_windows:
                issue(key, "No recibe visitas este día", label, "availability")
                return
            if (availability and availability.data.get("appointment_required")) or (
                not availability and potential and potential.data.get("appointment_required")
            ):
                issue(
                    key, "Requiere cita acordada; agéndala antes de incluirlo", label, "appointment"
                )
                return
            opens = min(w[0] for w in reception_windows)
            closes = max(w[1] for w in reception_windows)
        candidates.append(
            {
                "key": key,
                "kind": kind,
                "target_id": str(target_id),
                "institution_id": str(site.id),
                "label": label,
                "lat": site.lat,
                "lng": site.lng,
                "opens": opens,
                "closes": closes,
                "reception_windows": reception_windows,
                "service": service,
                "mandatory": fixed,
                "existing_visit_id": str(visit.id) if visit else None,
                "line_id": str(panel.default_line_id) if panel else None,
                "rule_id": str(rule.id) if rule else None,
                "priority": int(rule.data.get("priority", 1)) * 100 if rule else 1000,
                "product_sequence": rule.data.get("product_sequence", []) if rule else [],
                "availability_status": "provisional" if provisional else "confirmed",
                "address": site.address,
                "reason": "Cita fija"
                if fixed
                else "Horario por confirmar · frecuencia del panel"
                if provisional
                else "Impacto exigible dentro de su ventana de frecuencia",
            }
        )
        if potential:
            summary = potential_summary(potential.data)
            if not summary["stale"]:
                candidates[-1]["priority"] += summary["score"] or 0

    # Las visitas reales y las citas existentes siempre se consideran antes del panel.
    for kind, visits in [("doctor", medical), ("pharmacy", channel)]:
        for visit in visits:
            fingerprints.append(
                [
                    str(visit.id),
                    visit.status,
                    visit.scheduled_at.isoformat(),
                    visit.updated_at.isoformat(),
                ]
            )
            if visit.scheduled_at.astimezone(ZONE).date() != day:
                continue
            target = visit.doctor_id if kind == "doctor" else visit.pharmacy_id
            key = f"{kind}:{target}" + (
                f":{visit.institution_id}" if kind == "doctor" and visit.institution_id else ""
            )
            if visit.status == "not_done":
                replaced = visit.planned_by == "routing" and (
                    visit.not_done_reason == "rescheduled"
                    if kind == "doctor"
                    else bool((visit.report or {}).get("replanned"))
                )
                if not replaced:
                    seen.add(key)
                continue
            if visit.status != "scheduled":
                seen.add(key)
                doc = await session.get(Doctor, target) if kind == "doctor" else None
                pdv = await session.get(Pharmacy, target) if kind == "pharmacy" else None
                site = await session.get(
                    Institution, visit.institution_id if kind == "doctor" else pdv.institution_id
                )
                when = visit.arrived_at or visit.scheduled_at
                finish = visit.finished_at or max(
                    when
                    + timedelta(minutes=data["medical_minutes" if doc else "pharmacy_minutes"]),
                    clock.now(),
                )
                lat, lng = execution_point(visit, kind, site)
                locked.append(
                    {
                        "key": key,
                        "kind": kind,
                        "target_id": str(target),
                        "label": doc.full_name if doc else site.name,
                        "lat": lat,
                        "lng": lng,
                        "visit_id": str(visit.id),
                        "arrival_at": when.isoformat(),
                        "departure_at": finish.isoformat(),
                        "locked": True,
                        "status": visit.status,
                        "reason": "Visita iniciada o realizada: se conserva",
                    }
                )
            elif visit.planned_by != "routing":
                await candidate(kind, target, visit=visit)
    # Marketing is a fixed destination with service time, not a fictitious medical visit.
    from uno.modules.marketing.models import MarketingActivity
    from uno.modules.marketing.schemas import KINDS

    activities = (
        await session.scalars(
            select(MarketingActivity).where(
                MarketingActivity.representative_id == rep,
                MarketingActivity.starts_at >= instant(day, 0),
                MarketingActivity.starts_at < instant(day + timedelta(days=1), 0),
                MarketingActivity.status.in_(["scheduled", "in_progress", "completed"]),
            )
        )
    ).all()
    for activity in activities:
        fingerprints.append([str(activity.id), activity.version])
        site = await session.get(Institution, activity.institution_id)
        geo = await session.get(LocationVerification, activity.institution_id)
        fingerprints.append([str(site.id), site.lat, site.lng, geo.version if geo else None])
        a, b = (
            minute(activity.starts_at.astimezone(ZONE)),
            minute(activity.ends_at.astimezone(ZONE)),
        )
        item = {
            "key": f"marketing:{activity.id}",
            "kind": "marketing",
            "target_id": str(activity.id),
            "institution_id": str(site.id),
            "label": KINDS[activity.kind] + " · " + site.name,
            "lat": site.lat,
            "lng": site.lng,
            "address": site.address,
            "existing_visit_id": str(activity.id),
            "activity_version": activity.version,
            "line_id": str(activity.line_id),
            "status": activity.status,
            "product_sequence": [],
            "availability_status": "confirmed",
            "reason": "Actividad de mercadeo con horario fijo",
        }
        if activity.status != "scheduled":
            finish = activity.completed_at or max(activity.ends_at, clock.now())
            item.update(
                visit_id=str(activity.id),
                locked=True,
                arrival_at=(activity.started_at or activity.starts_at).isoformat(),
                departure_at=finish.isoformat(),
            )
            locked.append(item)
        elif not geo or geo.status != "verified" or not bogota_point(site.lat, site.lng):
            issue(
                item["key"],
                "Verifica la sede de la actividad de mercadeo",
                item["label"],
                "fixed_location",
            )
        elif a < start:
            issue(
                item["key"],
                "La actividad no ha comenzado y su horario ya pasó. Iníciala, reprograma o cancela",
                item["label"],
                "missed_appointment",
            )
        else:
            item.update(
                opens=a,
                closes=b,
                reception_windows=[[a, b]],
                service=b - a,
                mandatory=True,
                priority=10000,
            )
            candidates.append(item)
    locked.sort(key=lambda x: x["departure_at"])
    if locked:
        last = locked[-1]
        start = max(start, minute(datetime.fromisoformat(last["departure_at"]).astimezone(ZONE)))
        if last["lat"] is not None:
            origin = {"lat": last["lat"], "lng": last["lng"]}
    for rule in rules:
        kind = "doctor" if rule.doctor_id else "pharmacy"
        target = rule.doctor_id or rule.pharmacy_id
        rule_site = rule.institution_id
        if kind == "doctor" and not rule_site:
            rule_doc = await session.get(Doctor, target)
            rule_site = rule_doc.institution_id if rule_doc else None
        key = f"{kind}:{target}" + (f":{rule_site}" if rule_site else "")
        if key in seen:
            continue
        history = [
            v
            for v in (medical if kind == "doctor" else channel)
            if (v.doctor_id if kind == "doctor" else v.pharmacy_id) == target
            and (
                not rule.institution_id
                or kind != "doctor"
                or v.institution_id == rule.institution_id
            )
            and v.status != "not_done"
        ]
        other_days = [
            v.scheduled_at.astimezone(ZONE).date()
            for v in history
            if v.scheduled_at.astimezone(ZONE).date() != day
        ]
        # Import evidence informs the gap without fabricating a completed VisiMed visit.
        last_reported = rule.data.get("last_visit_on")
        if last_reported:
            other_days.append(date.fromisoformat(last_reported))
        matching = [
            w
            for w in rule.data["windows"]
            if date.fromisoformat(w["start"]) <= day <= date.fromisoformat(w["end"])
        ]
        if not matching:
            issue(key, "Fuera de la ventana de secuencia aprobada", code="sequence")
            continue
        window = matching[0]
        if any(
            date.fromisoformat(window["start"]) <= d <= date.fromisoformat(window["end"])
            for d in other_days
        ):
            issue(key, "El impacto de esta ventana ya está cubierto o agendado", code="covered")
            continue
        if any(abs((day - d).days) < rule.data["min_gap_days"] for d in other_days):
            issue(key, "No cumple la separación mínima entre impactos", code="frequency")
            continue
        existing = next(
            (
                v
                for v in history
                if v.scheduled_at.astimezone(ZONE).date() == day and v.status == "scheduled"
            ),
            None,
        )
        await candidate(kind, target, rule, existing)
    candidates.sort(key=lambda x: (not x["mandatory"], -x["priority"], x["key"]))
    if len(candidates) > 200:
        for c in candidates[200:]:
            issue(
                c["key"],
                "Pendiente de una siguiente planificación: límite de 200 candidatos",
                c["label"],
                "capacity",
            )
        candidates = candidates[:200]
    return {
        "policy": policy,
        "data": data,
        "origin": origin,
        "start": start,
        "locked": locked,
        "candidates": candidates,
        "issues": issues,
        "hash": cache_key([day, rep, fingerprints, candidates, [x["visit_id"] for x in locked]]),
    }


async def calculate(ctx, job_id):
    async with ctx.sessionmaker() as session:
        job = await session.get(RouteJob, job_id)
        info = await inputs(session, job.representative_id, job.day)
        previous = (
            await session.execute(
                select(RoutePlan)
                .where(
                    RoutePlan.representative_id == job.representative_id, RoutePlan.day == job.day
                )
                .order_by(RoutePlan.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if (
            previous
            and previous.input_hash == info["hash"]
            and previous.max_contacts == job.max_contacts
        ):
            job.plan_id = previous.id
            job.status = "done"
            job.lease_until = None
            await session.commit()
            return
        candidates = info["candidates"]
        points = [(info["origin"]["lat"], info["origin"]["lng"])] + [
            (c["lat"], c["lng"]) for c in candidates
        ]
        data = info["data"]
        if data["return_to_origin"]:
            points.append((data["origin"]["lat"], data["origin"]["lng"]))
        matrix = (
            await driving_matrix(ctx.settings, session, points)
            if candidates
            else {"minutes": [[0]], "meters": [[0]], "provider": "sin trayectos", "traffic": False}
        )
        remaining = max(0, job.max_contacts - sum(s["kind"] != "marketing" for s in info["locked"]))
        solution = await asyncio.to_thread(
            optimize,
            candidates,
            matrix,
            start=info["start"],
            end=minute(data["ends"]),
            lunch_start=minute(data["lunch_starts"]),
            lunch_end=minute(data["lunch_ends"]),
            max_contacts=remaining,
            max_medical=max(0, 10 - sum(x["kind"] == "doctor" for x in info["locked"])),
            max_pharmacies=max(0, 5 - sum(x["kind"] == "pharmacy" for x in info["locked"])),
            return_to_origin=data["return_to_origin"],
            end_index=len(points) - 1 if data["return_to_origin"] else 0,
        )
        # No publicar un cálculo cuyos insumos cambiaron mientras el proveedor respondía.
        await next_change_seq(session)
        async with ctx.sessionmaker() as check:
            fresh = await inputs(check, job.representative_id, job.day)
        if fresh["hash"] != info["hash"]:
            raise ApiError(
                409, "stale_inputs", "Los datos cambiaron durante el cálculo; se volverá a calcular"
            )
        await next_change_seq(session)
        plan = RoutePlan(
            id=uuid7(),
            representative_id=job.representative_id,
            day=job.day,
            version=(previous.version + 1 if previous else 1),
            input_hash=info["hash"],
            policy_version=info["policy"].version,
            max_contacts=job.max_contacts,
            created_at=clock.now(),
        )
        stops = list(info["locked"])
        for c in solution["stops"]:
            c["arrival_at"] = instant(job.day, c["arrival_minute"]).isoformat()
            c["departure_at"] = instant(job.day, c["departure_minute"]).isoformat()
            c["locked"] = False
            stops.append(c)
        dropped = set(solution["dropped"])
        issues = info["issues"] + [
            {
                "key": c["key"],
                "label": c["label"],
                "code": "capacity",
                "reason": "Sin asignar en el plan encontrado: revisar jornada, citas y capacidad",
            }
            for c in candidates
            if c["key"] in dropped
        ]
        if not solution["feasible"]:
            issues.append({"code": "infeasible", "reason": solution["reason"]})
        if not stops:
            issues.append(
                {
                    "code": "no_ready_contacts",
                    "reason": "No hay contactos elegibles con ubicación, horario y frecuencia "
                    "válidos. Completa los pendientes del panel.",
                }
            )
        for kind, minimum, label in [("doctor", 5, "médicos"), ("pharmacy", 2, "droguerías")]:
            if sum(s["kind"] == kind for s in stops) < minimum:
                issues.append(
                    {
                        "code": "coverage",
                        "label": "Cobertura de la jornada",
                        "reason": f"No se alcanzaron {minimum} {label} "
                        "con los contactos y horarios disponibles.",
                    }
                )
        plan.stops = stops
        plan.issues = issues
        plan.metrics = {
            "travel_minutes": solution.get("travel_minutes", 0),
            "provider": matrix["provider"],
            "traffic": False,
            "origin": info["origin"],
            "destination": data["origin"] if data["return_to_origin"] else None,
            "lunch": [data["lunch_starts"], data["lunch_ends"]],
            "return_to_origin": data["return_to_origin"],
            "feasible": solution["feasible"],
            "end_minute": solution.get("finish"),
            "calculated_at": clock.now().isoformat(),
        }
        from uno.modules.workflows.execution import plan_changes

        previous = await session.scalar(
            select(RoutePlan)
            .where(
                RoutePlan.representative_id == job.representative_id,
                RoutePlan.day == job.day,
                RoutePlan.status == "published",
            )
            .order_by(RoutePlan.version.desc())
            .limit(1)
        )
        plan.metrics = {
            **plan.metrics,
            "previous_version": previous.version if previous else None,
            "changes": plan_changes(previous, stops) if previous else [],
        }
        session.add(plan)
        await session.flush()
        job = await session.get(RouteJob, job_id)
        job.plan_id = plan.id
        job.status = "done"
        job.lease_until = None
        job.error = None
        # Citas perdidas y citas sin ubicación nunca desaparecen tras una autopublicación.
        blockers = any(
            x["code"].startswith("fixed_") or x["code"] in {"missed_appointment", "infeasible"}
            for x in issues
        )
        if (
            info["policy"].active
            and data["publish_automatically"]
            and job.max_contacts <= 12
            and solution["feasible"]
            and bool(stops)
            and not blockers
        ):
            actor = await session.get(User, info["policy"].approved_by)
            await publish(
                session,
                actor,
                plan.id,
                plan.version,
                "Publicación automática bajo política aprobada",
                automatic=True,
                skip_hash=True,
            )
        await session.commit()


async def publish(session, actor, plan_id, expected, reason, automatic=False, skip_hash=False):
    plan = await session.get(RoutePlan, plan_id)
    if not plan:
        raise ApiError(404, "not_found", "No se encontró el plan")
    if expected != plan.version:
        raise ApiError(409, "version_conflict", "La versión de la ruta cambió")
    if plan.status == "published":
        return {"id": str(plan.id), "version": plan.version, "status": plan.status}
    if plan.status != "draft":
        raise ApiError(409, "stale_plan", "Este plan ya fue reemplazado")
    if not plan.metrics["feasible"]:
        raise ApiError(422, "infeasible", "No se puede publicar una ruta inviable")
    if not plan.stops:
        raise ApiError(
            422,
            "no_ready_contacts",
            "Completa los datos pendientes: no hay paradas válidas para publicar",
        )
    if any(
        x["code"] == "missed_appointment" or x["code"].startswith("fixed_") for x in plan.issues
    ):
        raise ApiError(
            422, "fixed_appointment", "Resuelve las citas con incidencias antes de publicar"
        )
    if plan.max_contacts > 12 and (automatic or len(reason.strip()) < 10):
        raise ApiError(
            422,
            "approval_required",
            "La excepción requiere aprobación gerencial y motivo de al menos 10 caracteres",
        )
    fresh = await inputs(session, plan.representative_id, plan.day)
    if not skip_hash and fresh["hash"] != plan.input_hash:
        raise ApiError(
            409, "stale_inputs", "Cambiaron los datos o la agenda. Calcula una nueva versión"
        )
    if sum(s["kind"] != "marketing" for s in plan.stops) > plan.max_contacts:
        raise ApiError(422, "capacity", "La ruta excede la capacidad autorizada")
    if any(
        not s.get("locked") and datetime.fromisoformat(s["arrival_at"]) < clock.now()
        for s in plan.stops
    ):
        raise ApiError(
            409, "stale_schedule", "El horario de la propuesta ya pasó. Calcula una nueva versión"
        )
    seq = await next_change_seq(session)
    published = (
        (
            await session.execute(
                select(RoutePlan).where(
                    RoutePlan.representative_id == plan.representative_id,
                    RoutePlan.day == plan.day,
                    RoutePlan.status == "published",
                )
            )
        )
        .scalars()
        .all()
    )
    new_stops = []
    kept = set()
    for item in plan.stops:
        stop = dict(item)
        if stop["kind"] == "marketing":
            from uno.modules.marketing.models import MarketingActivity

            activity = await session.get(MarketingActivity, uuid.UUID(stop["target_id"]))
            if (
                activity is None
                or activity.version != stop["activity_version"]
                or activity.status == "cancelled"
            ):
                raise ApiError(
                    409, "stale_activity", "Cambió una actividad de mercadeo. Recalcula la ruta"
                )
            stop["visit_id"] = str(activity.id)
            kept.add(str(activity.id))
            new_stops.append(stop)
            continue
        if stop.get("locked"):
            kept.add(stop["visit_id"])
            new_stops.append(stop)
            continue
        id = uuid.UUID(stop["existing_visit_id"]) if stop.get("existing_visit_id") else uuid7()
        if stop["kind"] == "doctor":
            visit = await session.get(Visit, id)
            if visit:
                if visit.status != "scheduled":
                    raise ApiError(409, "visit_started", "Una visita ya empezó; recalcula")
                if visit.planned_by != "routing" and visit.scheduled_at != datetime.fromisoformat(
                    stop["arrival_at"]
                ):
                    raise ApiError(
                        409, "fixed_appointment", "Una cita fija no puede moverse automáticamente"
                    )
                visit.scheduled_at = datetime.fromisoformat(stop["arrival_at"])
                visit.updated_at = clock.now()
                visit.change_seq = seq
            else:
                visit = Visit(
                    id=id,
                    representative_id=plan.representative_id,
                    doctor_id=uuid.UUID(stop["target_id"]),
                    institution_id=uuid.UUID(stop["institution_id"]),
                    primary_line_id=uuid.UUID(stop["line_id"]),
                    scheduled_at=datetime.fromisoformat(stop["arrival_at"]),
                    title="Ruta automática",
                    planned_by="routing",
                    status="scheduled",
                    created_at=clock.now(),
                    updated_at=clock.now(),
                    change_seq=seq,
                )
                session.add(visit)
                await session.flush()
                session.add(
                    VisitLine(
                        visit_id=id,
                        line_id=uuid.UUID(stop["line_id"]),
                        role="planned",
                        source="agenda",
                    )
                )
        else:
            visit = await session.get(PharmacyVisit, id)
            if visit:
                if visit.status != "scheduled":
                    raise ApiError(409, "visit_started", "Una visita ya empezó; recalcula")
                visit.scheduled_at = datetime.fromisoformat(stop["arrival_at"])
                visit.version += 1
                visit.updated_at = clock.now()
            else:
                session.add(
                    PharmacyVisit(
                        id=id,
                        pharmacy_id=uuid.UUID(stop["target_id"]),
                        representative_id=plan.representative_id,
                        scheduled_at=datetime.fromisoformat(stop["arrival_at"]),
                        status="scheduled",
                        planned_by="routing",
                        updated_at=clock.now(),
                        version=1,
                    )
                )
        stop["visit_id"] = str(id)
        kept.add(str(id))
        new_stops.append(stop)
    for old in published:
        for stop in old.stops:
            if stop["kind"] == "marketing":
                continue
            vid = stop.get("visit_id")
            if not vid or vid in kept or stop.get("locked"):
                continue
            visit = await session.get(
                Visit if stop["kind"] == "doctor" else PharmacyVisit, uuid.UUID(vid)
            )
            if visit and visit.status == "scheduled":
                if visit.planned_by != "routing":
                    raise ApiError(409, "fixed_appointment", "No se puede retirar una cita manual")
                visit.status = "not_done"
                visit.updated_at = clock.now()
                if stop["kind"] == "doctor":
                    visit.not_done_reason = "rescheduled"
                    visit.change_seq = seq
                else:
                    visit.version += 1
                    visit.report = {"replanned": True}
        old.status = "superseded"
    plan.stops = new_stops
    plan.status = "published"
    plan.published_at = clock.now()
    plan.approval = {
        "actor_id": str(actor.id),
        "reason": reason,
        "automatic": automatic,
        "policy_version": plan.policy_version,
        "max_contacts": plan.max_contacts,
        "at": clock.now().isoformat(),
    }
    await emit(
        session,
        event_type="route_published",
        occurred_at=clock.now(),
        recorded_at=clock.now(),
        actor_type="system" if automatic else "user",
        actor_id=actor.id,
        entities={"route_id": str(plan.id), "representative_id": str(plan.representative_id)},
        payload={"version": plan.version, "stops": len(new_stops), "automatic": automatic},
        source="territory",
    )
    return {"id": str(plan.id), "version": plan.version, "status": plan.status}


async def run_cycle(ctx):
    now = clock.now()
    day = now.astimezone(ZONE).date()
    async with ctx.sessionmaker() as session:
        # Un productor a la vez. Esta transacción termina antes de consultar el proveedor.
        await next_change_seq(session)
        policies = (
            (await session.execute(select(RoutePolicy).where(RoutePolicy.active.is_(True))))
            .scalars()
            .all()
        )
        for p in policies:
            if p.data.get("ends_on") and day >= date.fromisoformat(p.data["ends_on"]):
                days = [day] if working_day(p.data, day) else []
            else:
                days = [day, next_working_day(p.data, day)]
            # Siempre mantener preparada la próxima jornada; no reconstruir días ya cerrados.
            for target in days:
                if working_day(p.data, target) and (
                    target > day or minute(now.astimezone(ZONE)) < minute(p.data["ends"])
                ):
                    await enqueue(
                        session,
                        p.representative_id,
                        target,
                        f"daily:{p.representative_id}:{target}:{p.version}",
                    )
            events = (
                (
                    await session.execute(
                        select(DomainEvent).where(
                            DomainEvent.recorded_at >= now - timedelta(days=1),
                            DomainEvent.event_type.in_(
                                [
                                    "visit_scheduled",
                                    "visit_arrived",
                                    "visit_not_done",
                                    "visit_rescheduled",
                                    "visit_finished",
                                    "visit_location_retried",
                                ]
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for event in events:
                # A manager/system can act for a rep: ownership is carried by
                # the event's entities, not necessarily by the actor.
                owner = event.entities.get("representative_id") or str(event.actor_id)
                if str(owner) != str(p.representative_id):
                    continue
                if p.data.get("ends_on") and day >= date.fromisoformat(p.data["ends_on"]):
                    continue
                for target in event_days(event, p.data, day):
                    if working_day(p.data, target) and (
                        target > day or minute(now.astimezone(ZONE)) < minute(p.data["ends"])
                    ):
                        await enqueue(
                            session, p.representative_id, target, f"event:{event.event_id}:{target}"
                        )
        job = (
            await session.execute(
                select(RouteJob)
                .where(
                    or_(
                        RouteJob.status == "queued",
                        (RouteJob.status == "running") & (RouteJob.lease_until < now),
                    ),
                    RouteJob.next_attempt <= now,
                    RouteJob.attempts < 3,
                )
                .order_by(RouteJob.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        job_id = job.id if job else None
        if job:
            job.status = "running"
            job.attempts += 1
            job.lease_until = now + timedelta(minutes=3)
        await session.commit()
    if job_id:
        try:
            await calculate(ctx, job_id)
        except Exception as exc:
            async with ctx.sessionmaker() as session:
                job = await session.get(RouteJob, job_id)
                job.status = "queued" if job.attempts < 3 else "error"
                job.lease_until = None
                job.next_attempt = clock.now() + timedelta(seconds=30 * job.attempts)
                job.error = (
                    exc.detail["message"][:500]
                    if isinstance(exc, ApiError)
                    else "No se pudo calcular la ruta. La ruta publicada se conserva."
                )
                await session.commit()
            if not isinstance(exc, ApiError):
                import logging

                logging.getLogger("uno.territory").exception("Error de cálculo de ruta")
    return {"processed": bool(job_id)}
