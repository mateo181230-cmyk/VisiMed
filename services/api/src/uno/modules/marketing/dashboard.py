"""Management measures from scoped operational records, never generated sample data."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from uno import clock
from uno.errors import ApiError
from uno.modules.agenda.models import Visit
from uno.modules.auth.models import User
from uno.modules.auth.permissions import (
    line_ids,
    representative_ids,
    require_capability,
    require_representative,
)
from uno.modules.calls.models import VisitReport
from uno.modules.catalog.models import Doctor, Institution, Panel
from uno.modules.territory.models import (
    LocationVerification,
    PanelContact,
    PharmacyVisit,
    Pharmacy,
    ReceptionAvailability,
    RoutePlan,
)
from uno.modules.territory.service import ZONE
from uno.modules.workflows.models import FollowupTask

from .models import MarketingActivity
from .schemas import KINDS


def date_bounds(start: date, end: date):
    if end < start or (end - start).days > 92:
        raise ApiError(
            422, "date_range", "Selecciona un período de hasta 93 días, en orden cronológico"
        )
    return datetime.combine(start, time(), ZONE), datetime.combine(
        end + timedelta(days=1), time(), ZONE
    )


def pct(part, total):
    return round(100 * part / total, 1) if total else None


async def snapshot(session, actor, start, end, representative_id=None, demo=False):
    require_capability(actor, "dashboard.read")
    if representative_id and not demo:
        require_representative(actor, representative_id)
    reps = [representative_id] if representative_id else representative_ids(actor)
    if demo:
        import uuid
        allowed = [uuid.UUID(x) for x in (actor.pilot_scope or {}).get("demo_representative_ids", [])]
        if not allowed or (representative_id and representative_id not in allowed):
            raise ApiError(403, "demo_scope", "Tu cuenta no tiene una demostración asignada")
        reps = [representative_id] if representative_id else allowed
    lines = line_ids(actor)
    lower, upper = date_bounds(start, end)
    now, today = clock.now(), clock.now().astimezone(ZONE).date()
    users = (
        await session.scalars(
            select(User).where(User.id.in_(reps), User.role == "rep").order_by(User.full_name)
        )
    ).all()
    names = {x.id: x.full_name for x in users}
    visits = (
        await session.scalars(
            select(Visit).where(
                Visit.representative_id.in_(reps),
                Visit.primary_line_id.in_(lines),
                Visit.scheduled_at >= lower,
                Visit.scheduled_at < upper,
            )
        )
    ).all()
    demo_sites=set((await session.scalars(select(Institution.id).where(Institution.ref_source.in_(['demo','demo_copy'])))).all())
    is_demo=lambda v:v.planned_by=='demo' or v.institution_id in demo_sites
    visits = [v for v in visits if is_demo(v)] if demo else [v for v in visits if not is_demo(v)]
    report_rows = (
        await session.scalars(
            select(VisitReport).where(VisitReport.visit_id.in_([v.id for v in visits]))
        )
    ).all()
    reports = {r.visit_id: r for r in report_rows}
    contacts = (
        await session.scalars(
            select(PanelContact)
            .join(
                Panel,
                (Panel.doctor_id == PanelContact.doctor_id)
                & (Panel.representative_id == PanelContact.representative_id),
            )
            .where(
                PanelContact.representative_id.in_(reps),
                PanelContact.active.is_(True),
                Panel.default_line_id.in_(lines),
            )
        )
    ).all()
    sites = {r.institution_id for r in contacts}
    verified = set(
        (
            await session.scalars(
                select(LocationVerification.institution_id).where(
                    LocationVerification.institution_id.in_(sites),
                    LocationVerification.status == "verified",
                )
            )
        ).all()
    )
    availability = (
        await session.scalars(
            select(ReceptionAvailability).where(ReceptionAvailability.institution_id.in_(sites))
        )
    ).all()
    hours = {(a.doctor_id, a.institution_id) for a in availability if a.data.get("reception")}
    activities = (
        await session.scalars(
            select(MarketingActivity).where(
                MarketingActivity.representative_id.in_(reps),
                MarketingActivity.line_id.in_(lines),
                MarketingActivity.starts_at >= lower,
                MarketingActivity.starts_at < upper,
            )
        )
    ).all()
    pharmacy = (
        await session.scalars(
            select(PharmacyVisit).where(
                PharmacyVisit.representative_id.in_(reps),
                PharmacyVisit.scheduled_at >= lower,
                PharmacyVisit.scheduled_at < upper,
            )
        )
    ).all()
    tasks = (
        await session.scalars(
            select(FollowupTask)
            .join(Visit, FollowupTask.visit_id == Visit.id)
            .where(FollowupTask.representative_id.in_(reps), Visit.primary_line_id.in_(lines))
        )
    ).all()
    plans = (
        await session.scalars(
            select(RoutePlan).where(
                RoutePlan.representative_id.in_(reps),
                RoutePlan.day >= start,
                RoutePlan.day <= end,
                RoutePlan.status == "published",
            )
        )
    ).all()
    from .metrics import operational, measures
    demo_pharmacies=set((await session.scalars(select(Pharmacy.id).where(Pharmacy.institution_id.in_(demo_sites)))).all())
    contacts=[c for c in contacts if (c.institution_id in demo_sites)==demo]
    activities=[a for a in activities if bool(a.data.get('demo') or a.institution_id in demo_sites)==demo]
    pharmacy=[p for p in pharmacy if bool(p.planned_by=='demo' or p.pharmacy_id in demo_pharmacies)==demo]
    tasks = [t for t in tasks if t.visit_id in {v.id for v in visits}]
    excluded_history = sum(not operational(v, reports.get(v.id)) for v in visits)
    visits = visits if demo else [v for v in visits if operational(v, reports.get(v.id))]
    finished = [v for v in visits if v.finished_at is not None and v.status != "not_done"]
    confirmed = [v for v in finished if v.id in reports and reports[v.id].status == "confirmed"]
    completed = [a for a in activities if a.status == "completed"]
    open_tasks = [t for t in tasks if t.status in ("open", "in_progress")]
    overdue = [t for t in open_tasks if t.due_on and t.due_on < today]
    panel_doctors = {c.doctor_id for c in contacts}
    covered = panel_doctors & {v.doctor_id for v in finished}
    attendees = [p for a in completed for p in a.data.get("attendees", [])]
    counts = {
        "scheduled_visits": len([v for v in visits if v.status != "not_done"]),
        "finished_visits": len(finished),
        "cancelled_visits": sum(v.status == "not_done" for v in visits),
        "confirmed_reports": len(confirmed),
        "pending_reports": len(finished) - len(confirmed),
        "report_rate": pct(len(confirmed), len(finished)),
        "panel_doctors": len(panel_doctors),
        "covered_doctors": len(covered),
        "coverage_rate": pct(len(covered), len(panel_doctors)),
        "pharmacy_finished": sum(
            p.finished_at is not None and p.status != "not_done" for p in pharmacy
        ),
        "marketing_planned": sum(a.status not in ("draft", "cancelled") for a in activities),
        "marketing_completed": len(completed),
        "attendances": len(attendees),
        "panel_attendances": sum(bool(a.get("doctor_id")) for a in attendees),
        "external_attendances": sum(not a.get("doctor_id") for a in attendees),
        "unique_panel_attendees": len({a["doctor_id"] for a in attendees if a.get("doctor_id")}),
        "open_tasks": len(open_tasks),
        "overdue_tasks": len(overdue),
        "panel_sites": len(contacts),
        "verified_locations": sum(c.institution_id in verified for c in contacts),
        "confirmed_hours": sum((c.doctor_id, c.institution_id) in hours for c in contacts),
    }
    trend = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)

        def at(value, day=day):
            return value.astimezone(ZONE).date() == day

        trend.append(
            {
                "day": day.isoformat(),
                "planned": sum(at(v.scheduled_at) and v.status != "not_done" for v in visits),
                "finished": sum(at(v.scheduled_at) for v in finished),
                "reports": sum(at(v.scheduled_at) for v in confirmed),
                "marketing": sum(at(a.starts_at) for a in completed),
            }
        )
    team = []
    for id, name in names.items():
        own = [v for v in finished if v.representative_id == id]
        docs = {c.doctor_id for c in contacts if c.representative_id == id}
        done = [a for a in completed if a.representative_id == id]
        team.append(
            {
                "id": str(id),
                "name": name,
                "finished": len(own),
                "reports": sum(v.representative_id == id for v in confirmed),
                "covered": len(docs & {v.doctor_id for v in own}),
                "panel": len(docs),
                "marketing": len(done),
                "attendances": sum(len(a.data.get("attendees", [])) for a in done),
                "overdue": sum(t.representative_id == id for t in overdue),
            }
        )
    product_counts, specialty_counts, kind_counts = Counter(), Counter(), Counter()
    for a in completed:
        kind_counts[KINDS[a.kind]] += 1
        for product in a.data.get("products", []):
            product_counts[product["name"]] += len(a.data.get("attendees", []))
        specialty_counts.update(x["specialty"] for x in a.data.get("attendees", []))
    alerts = []
    if counts["pending_reports"]:
        alerts.append(
            {
                "level": "warning",
                "title": f"{counts['pending_reports']} visitas sin reporte confirmado",
                "detail": "La visita está terminada, pero su resultado aún no está confirmado.",
                "target": "visits",
            }
        )
    if overdue:
        alerts.append(
            {
                "level": "warning",
                "title": f"{len(overdue)} compromisos vencidos",
                "detail": "Revisa el responsable y la evidencia pendiente.",
                "target": "tasks",
            }
        )
    missing_hours = counts["panel_sites"] - counts["confirmed_hours"]
    if missing_hours:
        alerts.append(
            {
                "level": "info",
                "title": f"{missing_hours} contactos sin horario confirmado",
                "detail": "No son elegibles para la ruta automática hasta confirmar recepción.",
                "target": "route",
            }
        )
    unverified = counts["panel_sites"] - counts["verified_locations"]
    if unverified:
        alerts.append(
            {
                "level": "info",
                "title": f"{unverified} contactos con ubicación pendiente",
                "detail": "Valida sus sedes antes de incorporarlos a una ruta.",
                "target": "route",
            }
        )
    for a in activities:
        if a.status in ("scheduled", "in_progress") and a.ends_at < now:
            alerts.append(
                {
                    "level": "warning",
                    "title": "Actividad pendiente de cierre",
                    "detail": f"{KINDS[a.kind]} · {names.get(a.representative_id, '')}",
                    "target": "marketing",
                    "id": str(a.id),
                }
            )
    doctor_names = dict(
        (
            await session.execute(
                select(Doctor.id, Doctor.full_name).where(
                    Doctor.id.in_([v.doctor_id for v in visits])
                )
            )
        ).all()
    )
    place_names = dict(
        (
            await session.execute(
                select(Institution.id, Institution.name).where(
                    Institution.id.in_([a.institution_id for a in activities])
                )
            )
        ).all()
    )
    performance = await measures(session, reps, lines, start, end, visits, reports, plans, include_demo=demo)
    performance["excluded_history"] = excluded_history
    from .signals import signals
    from uno.modules.calls.snc_report import SNCReport
    report_evidence = []
    for v in sorted(confirmed, key=lambda x:x.scheduled_at, reverse=True)[:5]:
        raw = reports[v.id].fields.get("snc_report_json", {}).get("value")
        if not raw: continue
        try:
            evidence = SNCReport.model_validate_json(raw)
        except ValueError:
            continue
        report_evidence.append({"visit_id":str(v.id),"doctor":doctor_names.get(v.doctor_id),
            "at":v.scheduled_at.isoformat(), "products":[{"name":p.name,
                "objective":(p.objective or "")[:160], "achievement":p.achievement,
                "evidence":(p.evidence or "")[:180]} for p in evidence.products],
            "commitments":[{"owner":c.owner,"action":c.action[:160]} for c in (evidence.commitments or [])[:3]]})
    return {
        "recent_confirmed_reports": report_evidence,
        "mode": "demo" if demo else "pilot",
        "intelligence": signals(visits, reports, now, demo=demo),
        "performance": performance,
        "as_of": now.isoformat(),
        "timezone": "America/Bogota",
        "start": str(start),
        "end": str(end),
        "counts": counts,
        "profile": actor.management_profile,
        "team": team,
        "trend": trend,
        "alerts": alerts[:30],
        "products": [{"name": n, "value": v} for n, v in product_counts.most_common()],
        "specialties": [{"name": n, "value": v} for n, v in specialty_counts.most_common()],
        "activity_types": [{"name": n, "value": v} for n, v in kind_counts.most_common()],
        "routes": [
            {
                "id": str(p.id),
                "day": str(p.day),
                "rep": names.get(p.representative_id),
                "stops": len(p.stops),
                "estimated_travel_minutes": p.metrics.get("travel_minutes"),
                "version": p.version,
            }
            for p in plans
        ],
        "visits": [
            {
                "id": str(v.id),
                "doctor": doctor_names.get(v.doctor_id),
                "representative": names.get(v.representative_id),
                "at": v.scheduled_at.isoformat(),
                "status": v.status,
                "report_status": reports[v.id].status if v.id in reports else "pending",
                "finished": v.finished_at is not None,
            }
            for v in sorted(visits, key=lambda v: v.scheduled_at, reverse=True)
        ],
        "activities": [
            {
                "id": str(a.id),
                "institution": place_names.get(a.institution_id),
                "kind": KINDS[a.kind],
                "representative": names.get(a.representative_id),
                "at": a.starts_at.isoformat(),
                "status": a.status,
                "attendances": len(a.data.get("attendees", []))
                if a.status == "completed"
                else None,
            }
            for a in sorted(activities, key=lambda a: a.starts_at, reverse=True)
        ],
        "definitions": {
            "coverage": (
                "Médicos únicos del panel activo con visita terminada / médicos únicos "
                "del panel activo. La asistencia a mercadeo no completa frecuencia FZ."
            ),
            "report_rate": (
                "Reportes confirmados de visitas terminadas / visitas terminadas "
                "en el período seleccionado."
            ),
            "attendances": (
                "Asistencias registradas en actividades cerradas; una persona puede "
                "asistir a varias actividades. Las marcas pueden compartir asistentes."
            ),
            "tasks": (
                "Compromisos abiertos y vencidos a la fecha actual, "
                "sin limitar por el período del gráfico."
            ),
            "trend": (
                "Visitas agrupadas por fecha programada en Bogotá; mercadeo por fecha de inicio."
            ),
            "alerts": (
                "Reglas verificables sobre datos faltantes y pendientes; "
                "no es un modelo predictivo."
            ),
        },
        "sources": [
            {"name": "Visitas, reportes y mercadeo", "status": "Base operativa actual"},
            {"name": "Panel SNC", "status": "Panel importado y validaciones registradas"},
            {
                "name": "Ventas / Close-Up",
                "status": "Consulta los cortes comerciales en la vista de gerencia de línea; no se infieren ventas ni prescripción",
            },
            {
                "name": "Pharmadvisor",
                "status": "Exportación para conciliación; no se envían cambios automáticamente",
            },
        ],
    }
