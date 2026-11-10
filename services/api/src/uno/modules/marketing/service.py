from __future__ import annotations

from collections import Counter

from sqlalchemy import select

from uno import clock
from uno.errors import ApiError
from uno.modules.auth.models import User
from uno.modules.auth.permissions import (
    line_ids,
    representative_ids,
    require_capability,
    require_representative,
)
from uno.modules.catalog.models import Doctor, Institution, Panel, Product, ProductLine
from uno.modules.territory.models import (
    LocationVerification,
    PanelContact,
    RouteJob,
    RoutePlan,
    RoutePolicy,
)
from uno.modules.territory.providers import bogota_point
from uno.modules.territory.service import ZONE, audit, enqueue, row_json, version

from .models import MarketingActivity, MarketingRevision
from .schemas import KINDS, ActivityInput


def scope(query, actor):
    require_capability(actor, "marketing.read")
    reps, lines = representative_ids(actor), line_ids(actor)
    if reps is not None:
        query = query.where(MarketingActivity.representative_id.in_(reps))
    if lines is not None:
        query = query.where(MarketingActivity.line_id.in_(lines))
    return query


async def get_activity(session, actor, id):
    row = await session.scalar(
        scope(select(MarketingActivity).where(MarketingActivity.id == id), actor)
    )
    if not row:
        raise ApiError(404, "not_found", "No encontramos esta actividad en tu equipo")
    return row


async def render(session, row):
    result = row_json(row)
    site = await session.get(Institution, row.institution_id)
    rep = await session.get(User, row.representative_id)
    result.update(
        institution=site.name if site else "Sede",
        address=site.address if site else "",
        representative=rep.full_name if rep else "Visitador",
        kind_label=KINDS[row.kind],
    )
    result["specialties"] = dict(Counter(a["specialty"] for a in row.data.get("attendees", [])))
    result["panel_count"] = sum(bool(a.get("doctor_id")) for a in row.data.get("attendees", []))
    result["external_count"] = len(row.data.get("attendees", [])) - result["panel_count"]
    result["route_state"] = "not_required"
    if row.status in ("scheduled", "in_progress"):
        day = row.starts_at.astimezone(ZONE).date()
        latest = await session.scalar(
            select(RouteJob)
            .where(RouteJob.representative_id == row.representative_id, RouteJob.day == day)
            .order_by(RouteJob.created_at.desc())
            .limit(1)
        )
        plan = await session.get(RoutePlan, latest.plan_id) if latest and latest.plan_id else None
        included = (
            plan
            and plan.status == "published"
            and any(
                s.get("target_id") == str(row.id) and s.get("activity_version") == row.version
                for s in plan.stops
            )
        )
        result["route_state"] = (
            "included"
            if included
            else "pending"
            if latest and latest.status in ("queued", "running")
            else "review"
        )
        result["route_message"] = (
            "Incluida en la ruta publicada"
            if included
            else "Recalculando la ruta"
            if result["route_state"] == "pending"
            else "Revisa la ruta: la actividad aún no está incluida en una ruta viable"
        )
    return result


async def catalog(session, actor, rep):
    require_capability(actor, "marketing.read")
    allowed = representative_ids(actor)
    reps = (
        await session.scalars(
            select(User)
            .where(
                User.role == "rep",
                User.is_active.is_(True),
                User.id.in_(allowed) if allowed is not None else True,
            )
            .order_by(User.full_name)
        )
    ).all()
    chosen = rep or (actor.id if actor.role == "rep" else (reps[0].id if reps else None))
    if chosen:
        require_representative(actor, chosen)
    lines = (
        await session.scalars(
            select(ProductLine).where(
                ProductLine.active.is_(True),
                ProductLine.id.in_(line_ids(actor)) if line_ids(actor) is not None else True,
                ProductLine.code == "SNC",
            )
        )
    ).all()
    doctors = (
        (
            await session.scalars(
                select(Doctor)
                .join(Panel)
                .where(
                    Panel.representative_id == chosen,
                    Panel.default_line_id.in_([x.id for x in lines]),
                )
                .order_by(Doctor.full_name)
            )
        ).all()
        if chosen
        else []
    )
    contacts = (
        (
            await session.scalars(
                select(PanelContact).where(PanelContact.representative_id == chosen)
            )
        ).all()
        if chosen
        else []
    )
    sites = {d.institution_id for d in doctors if d.institution_id} | {
        c.institution_id for c in contacts
    }
    places = (
        await session.scalars(
            select(Institution).where(Institution.id.in_(sites)).order_by(Institution.name)
        )
    ).all()
    verified = set(
        (
            await session.scalars(
                select(LocationVerification.institution_id).where(
                    LocationVerification.status == "verified"
                )
            )
        ).all()
    )
    products = (
        await session.scalars(
            select(Product)
            .where(Product.line_id.in_([x.id for x in lines]), Product.active.is_(True))
            .order_by(Product.name)
        )
    ).all()
    return {
        "representative_id": str(chosen) if chosen else None,
        "representatives": [{"id": str(x.id), "name": x.full_name} for x in reps],
        "lines": [{"id": str(x.id), "name": x.name} for x in lines],
        "doctors": [
            {"id": str(x.id), "name": x.full_name, "specialty": x.specialty or ""} for x in doctors
        ],
        "sites": [
            {"id": str(x.id), "name": x.name, "address": x.address, "verified": x.id in verified}
            for x in places
        ],
        "products": [
            {"id": str(x.id), "name": x.name, "line_id": str(x.line_id)} for x in products
        ],
    }


async def save_activity(session, actor, command):
    require_capability(actor, "marketing.write")
    p = ActivityInput.model_validate(command.payload)
    require_representative(actor, p.representative_id)
    allowed_lines = line_ids(actor)
    line = await session.get(ProductLine, p.line_id)
    rep = await session.get(User, p.representative_id)
    if (
        not rep
        or rep.role != "rep"
        or not rep.is_active
        or not line
        or line.code != "SNC"
        or not line.active
        or (allowed_lines is not None and p.line_id not in allowed_lines)
    ):
        raise ApiError(
            403,
            "out_of_scope",
            "La actividad debe pertenecer a un visitador y a la línea SNC autorizados",
        )
    row = await session.get(MarketingActivity, p.id)
    if row:
        await get_activity(session, actor, p.id)
        if row.representative_id != p.representative_id or row.line_id != p.line_id:
            raise ApiError(
                409,
                "fixed_owner",
                "No puedes cambiar el responsable ni la línea de una actividad registrada",
            )
    version(row, command.expected_version)
    if row and row.status in ("completed", "cancelled"):
        raise ApiError(
            409,
            "closed_activity",
            "La actividad está cerrada y conserva su evidencia. "
            "Registra una nueva actividad si corresponde",
        )
    now = clock.now()
    previous_day = row.starts_at.astimezone(ZONE).date() if row else None
    if p.starts_at.astimezone(ZONE).date() != p.ends_at.astimezone(ZONE).date():
        raise ApiError(422, "same_day", "La actividad debe empezar y terminar el mismo día")
    if p.status in ("in_progress", "completed") and p.starts_at > now:
        raise ApiError(
            422, "future_result", "No puedes registrar ejecución antes del inicio programado"
        )
    if p.status == "in_progress" and (not row or row.status not in ("scheduled", "in_progress")):
        raise ApiError(422, "not_scheduled", "Programa la actividad antes de iniciarla")
    if (
        row
        and row.status == "in_progress"
        and p.status not in ("in_progress", "completed", "cancelled")
    ):
        raise ApiError(409, "already_started", "Finaliza o cancela la actividad que ya comenzaste")
    if (
        row
        and row.status == "in_progress"
        and (
            row.starts_at != p.starts_at
            or row.ends_at != p.ends_at
            or row.institution_id != p.institution_id
        )
    ):
        raise ApiError(
            409, "already_started", "Una actividad iniciada conserva su sede y su horario"
        )
    cat = await catalog(session, actor, p.representative_id)
    if str(p.institution_id) not in {x["id"] for x in cat["sites"]}:
        raise ApiError(403, "site_scope", "Selecciona una sede del territorio del visitador")
    products = {x["id"]: x for x in cat["products"] if x["line_id"] == str(p.line_id)}
    if any(str(id) not in products for id in p.product_ids):
        raise ApiError(422, "invalid_product", "Selecciona marcas SNC activas del catálogo")
    doctors = {x["id"]: x for x in cat["doctors"]}
    normalized_names = {x["name"].casefold() for x in cat["doctors"]}
    attendees = []
    for a in p.attendees:
        d = a.model_dump(mode="json")
        if a.doctor_id:
            doctor = doctors.get(str(a.doctor_id))
            if not doctor:
                raise ApiError(
                    403, "doctor_scope", "Uno de los asistentes no pertenece al panel autorizado"
                )
            d["name"] = doctor["name"]
        elif a.name.casefold() in normalized_names:
            raise ApiError(
                422,
                "panel_match",
                "Ese médico ya está en el panel. Selecciónalo en Médicos del panel",
            )
        attendees.append(d)
    if p.status in ("scheduled", "in_progress"):
        site = await session.get(Institution, p.institution_id)
        geo = await session.get(LocationVerification, p.institution_id)
        if (
            not geo
            or geo.status != "verified"
            or site.lat is None
            or site.lng is None
            or not bogota_point(site.lat, site.lng)
        ):
            raise ApiError(
                422,
                "unverified_location",
                "Verifica primero la ubicación de la sede en Sedes y mapa",
            )
        if p.status == "scheduled" and p.starts_at < now:
            raise ApiError(
                422,
                "past_schedule",
                "La hora de inicio ya pasó. "
                "Corrige el horario o registra el resultado si ya ocurrió",
            )
        overlap = await session.scalar(
            select(MarketingActivity.id)
            .where(
                MarketingActivity.id != p.id,
                MarketingActivity.representative_id == p.representative_id,
                MarketingActivity.status.in_(["scheduled", "in_progress"]),
                MarketingActivity.starts_at < p.ends_at,
                MarketingActivity.ends_at > p.starts_at,
            )
            .limit(1)
        )
        if overlap:
            raise ApiError(
                409, "agenda_conflict", "El visitador ya tiene otra actividad en ese horario"
            )
        policy = await session.get(RoutePolicy, p.representative_id)
        if not policy or not policy.active:
            raise ApiError(
                422, "missing_policy", "Activa la política de ruta del visitador antes de programar"
            )
        from uno.modules.territory.planning import minute, working_day

        start, end = minute(p.starts_at.astimezone(ZONE)), minute(p.ends_at.astimezone(ZONE))
        data = policy.data
        if (
            not working_day(data, p.starts_at.astimezone(ZONE).date())
            or start < minute(data["starts"])
            or end > minute(data["ends"])
            or (start < minute(data["lunch_ends"]) and end > minute(data["lunch_starts"]))
        ):
            raise ApiError(
                422,
                "workday_conflict",
                "El horario debe respetar la jornada y el almuerzo del visitador",
            )
    if row is None:
        row = MarketingActivity(
            id=p.id,
            representative_id=p.representative_id,
            line_id=p.line_id,
            version=0,
            created_by=actor.id,
            created_at=now,
        )
        session.add(row)
    for field in ("institution_id", "kind", "objective", "starts_at", "ends_at", "status"):
        setattr(row, field, getattr(p, field))
    if p.status == "in_progress" and not row.started_at:
        row.started_at = now
    if p.status == "completed":
        row.completed_at = now
    row.data = {
        "planned_attendees": p.planned_attendees,
        "products": [products[str(x)] for x in p.product_ids],
        "consultation_types": p.consultation_types,
        "attendees": attendees,
        "materials": [x.model_dump() for x in p.materials],
        "outcome": p.outcome,
        "next_action": p.next_action,
        "cancellation_reason": p.cancellation_reason,
        "pharmadvisor_status": "not_sent",
    }
    row.version += 1
    row.updated_by, row.updated_at = actor.id, now
    await session.flush()
    session.add(
        MarketingRevision(
            activity_id=row.id,
            version=row.version,
            actor_id=actor.id,
            snapshot=row_json(row),
            created_at=now,
        )
    )
    await audit(session, actor, "marketing_activity_saved", row.id, row.version)
    jobs = []
    if p.status != "draft" or previous_day:
        policy = await session.get(RoutePolicy, p.representative_id)
        if policy and policy.active:
            for day in sorted({p.starts_at.astimezone(ZONE).date(), previous_day} - {None}):
                if day >= now.astimezone(ZONE).date():
                    job = await enqueue(
                        session,
                        p.representative_id,
                        day,
                        f"marketing:{command.id}:{day}",
                        policy.data.get("max_contacts", 12),
                    )
                    jobs.append(str(job.id))
    return {
        "id": str(row.id),
        "version": row.version,
        "status": row.status,
        "route_jobs": jobs,
        "message": "Guardado. La ruta se recalcula; revisa su viabilidad antes de salir"
        if jobs
        else "Actividad guardada",
    }
