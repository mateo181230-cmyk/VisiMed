from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.db import next_change_seq
from uno.errors import ApiError
from uno.events import emit
from uno.ids import uuid7
from uno.modules.agenda.models import Visit
from uno.modules.auth.models import User
from uno.modules.auth.permissions import (
    capabilities,
    line_ids,
    permits,
    representative_ids,
    require_capability,
    require_representative,
)
from uno.modules.catalog.models import (
    CommercialCycle,
    Doctor,
    Institution,
    Panel,
    Product,
    ProductPresentation,
)

from .models import (
    LocationVerification,
    MedicalPotential,
    PanelContact,
    Pharmacy,
    PharmacyReferral,
    PharmacyVisit,
    ReceptionAvailability,
    RouteJob,
    RoutePlan,
    RoutePolicy,
    TerritoryCommand,
    VisitRequirement,
)
from .providers import bogota_point
from .schemas import (
    AvailabilityInput,
    Command,
    GenerateInput,
    PharmacyInput,
    PharmacyReport,
    PolicyInput,
    PotentialInput,
    PublishInput,
    ReferralInput,
    RequirementInput,
    SchedulePharmacy,
    VerifyLocation,
    VisitAction,
)

ZONE = ZoneInfo("America/Bogota")
MANAGERS = {"admin", "manager"}


def management(actor: User):
    if not permits(actor, "territory.manage"):
        raise ApiError(403, "manager_required", "Esta acción requiere gerencia")


def owner(actor: User, representative_id: uuid.UUID):
    require_representative(actor, representative_id)


def version(row, expected: int):
    actual = row.version if row else 0
    if expected != actual:
        raise ApiError(
            409, "version_conflict", "El registro cambió. Actualiza y revisa antes de guardar."
        )


async def doctor_access(session: AsyncSession, actor: User, id: uuid.UUID, representative_id=None):
    doctor = await session.get(Doctor, id)
    if not doctor:
        raise ApiError(404, "not_found", "No se encontró el médico")
    rep = representative_id or (actor.id if actor.role not in MANAGERS else None)
    if rep and not await session.get(Panel, (rep, id)):
        raise ApiError(403, "out_of_scope", "El médico no pertenece al panel del visitador")
    if rep:
        owner(actor, rep)
    allowed = representative_ids(actor)
    if rep is None and allowed is not None:
        visible = await session.scalar(
            select(Panel.doctor_id)
            .where(Panel.doctor_id == id, Panel.representative_id.in_(allowed))
            .limit(1)
        )
        if not visible:
            raise ApiError(403, "out_of_scope", "El médico no pertenece a tu equipo")
    return doctor


async def pharmacy_access(session: AsyncSession, actor: User, id: uuid.UUID):
    item = await session.get(Pharmacy, id)
    if not item:
        raise ApiError(404, "not_found", "No se encontró la droguería")
    owner(actor, item.representative_id)
    return item


async def site_access(session: AsyncSession, actor: User, id: uuid.UUID):
    site = await session.get(Institution, id)
    if not site:
        raise ApiError(404, "not_found", "No se encontró la sede")
    allowed = representative_ids(actor)
    if allowed is not None:
        medical = (
            await session.execute(
                select(Doctor.id)
                .join(Panel, Panel.doctor_id == Doctor.id)
                .where(Doctor.institution_id == id, Panel.representative_id.in_(allowed))
            )
        ).first()
        pharmacy = (
            await session.execute(
                select(Pharmacy.id).where(
                    Pharmacy.institution_id == id, Pharmacy.representative_id.in_(allowed)
                )
            )
        ).first()
        contact = (
            await session.execute(
                select(PanelContact.id).where(
                    PanelContact.institution_id == id,
                    PanelContact.representative_id.in_(allowed),
                )
            )
        ).first()
        if not medical and not pharmacy and not contact:
            raise ApiError(403, "out_of_scope", "La sede no pertenece a tu territorio")
    return site


async def doctor_site_access(session, actor, doctor_id, institution_id, representative_id=None):
    doctor = await doctor_access(session, actor, doctor_id, representative_id)
    if doctor.institution_id == institution_id:
        return doctor
    query = select(PanelContact.id).where(
        PanelContact.doctor_id == doctor_id,
        PanelContact.institution_id == institution_id,
    )
    rep = representative_id or (actor.id if actor.role not in MANAGERS else None)
    if rep:
        query = query.where(PanelContact.representative_id == rep)
    elif representative_ids(actor) is not None:
        query = query.where(PanelContact.representative_id.in_(representative_ids(actor)))
    if not (await session.execute(query)).first():
        raise ApiError(422, "site_mismatch", "La sede no pertenece a este médico")
    return doctor


async def audit(session, actor, kind, entity_id, revision=1):
    await emit(
        session,
        event_type=kind,
        occurred_at=clock.now(),
        recorded_at=clock.now(),
        actor_type="user",
        actor_id=actor.id,
        entities={"id": str(entity_id)},
        payload={"version": revision},
        source="territory",
    )


def potential_summary(data: dict) -> dict:
    weekly = len(data["practice_days"]) * data["patients_per_day"]
    share = data.get("snc_percentage")
    age = (clock.now().astimezone(ZONE).date() - date.fromisoformat(data["observed_on"])).days
    estimated = round(weekly * share / 100, 1) if share is not None else None
    return {
        "weekly_consultations": weekly,
        "weekly_snc_estimate": estimated,
        "score": round(min(100, estimated / 2)) if estimated is not None else None,
        "method": "regla-v1: atenciones SNC semanales / 2, máximo 100; "
        "no es ML ni intención de prescripción",
        "stale": age > 90,
        "age_days": age,
        "source": data["source"],
    }


def row_json(row):
    return {
        c.name: (
            v.isoformat() if hasattr(v, "isoformat") else str(v) if isinstance(v, uuid.UUID) else v
        )
        for c in row.__table__.columns
        for v in [getattr(row, c.name)]
    }


async def snapshot(session: AsyncSession, actor: User, representative_id=None):
    allowed = representative_ids(actor)
    reps = (
        (
            await session.execute(
                select(User)
                .where(
                    User.role == "rep",
                    User.is_active.is_(True),
                    User.id.in_(allowed) if allowed is not None else True,
                )
                .order_by(User.full_name)
            )
        )
        .scalars()
        .all()
        if actor.role in MANAGERS
        else [actor]
    )
    rep_id = representative_id or (reps[0].id if reps else actor.id)
    owner(actor, rep_id)
    panels = (
        await session.execute(
            select(Panel, Doctor)
            .join(Doctor, Doctor.id == Panel.doctor_id)
            .where(Panel.representative_id == rep_id)
        )
    ).all()
    contacts = (
        (
            await session.execute(
                select(PanelContact).where(PanelContact.representative_id == rep_id)
            )
        )
        .scalars()
        .all()
    )
    pharmacies = (
        (await session.execute(select(Pharmacy).where(Pharmacy.representative_id == rep_id)))
        .scalars()
        .all()
    )
    site_ids = (
        {d.institution_id for p, d in panels if d.institution_id}
        | {c.institution_id for c in contacts}
        | {p.institution_id for p in pharmacies}
    )
    sites = (
        (await session.execute(select(Institution).where(Institution.id.in_(site_ids))))
        .scalars()
        .all()
        if site_ids
        else []
    )
    geo = (
        (
            await session.execute(
                select(LocationVerification).where(
                    LocationVerification.institution_id.in_(site_ids)
                )
            )
        )
        .scalars()
        .all()
        if site_ids
        else []
    )
    potentials = (
        (
            await session.execute(
                select(MedicalPotential).where(
                    MedicalPotential.doctor_id.in_([d.id for p, d in panels])
                )
            )
        )
        .scalars()
        .all()
        if panels
        else []
    )
    rules = (
        (
            await session.execute(
                select(VisitRequirement).where(VisitRequirement.representative_id == rep_id)
            )
        )
        .scalars()
        .all()
    )
    visits = (
        (
            await session.execute(
                select(Visit)
                .where(
                    Visit.representative_id == rep_id,
                    Visit.scheduled_at >= clock.now() - timedelta(days=90),
                )
                .order_by(Visit.scheduled_at.desc())
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    pdv_visits = (
        (
            await session.execute(
                select(PharmacyVisit)
                .where(PharmacyVisit.representative_id == rep_id)
                .order_by(PharmacyVisit.scheduled_at.desc())
                .limit(300)
            )
        )
        .scalars()
        .all()
    )
    referrals = (
        (
            await session.execute(
                select(PharmacyReferral)
                .where(PharmacyReferral.representative_id == rep_id)
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    plans = (
        (
            await session.execute(
                select(RoutePlan)
                .where(RoutePlan.representative_id == rep_id)
                .order_by(RoutePlan.created_at.desc())
                .limit(60)
            )
        )
        .scalars()
        .all()
    )
    jobs = (
        (
            await session.execute(
                select(RouteJob)
                .where(RouteJob.representative_id == rep_id)
                .order_by(RouteJob.created_at.desc())
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    policy = await session.get(RoutePolicy, rep_id)
    from uno.modules.marketing.models import MarketingActivity
    from uno.modules.marketing.schemas import KINDS

    marketing = (
        await session.scalars(
            select(MarketingActivity)
            .where(
                MarketingActivity.representative_id == rep_id,
                MarketingActivity.starts_at >= clock.now() - timedelta(days=90),
                MarketingActivity.status != "draft",
            )
            .order_by(MarketingActivity.starts_at.desc())
            .limit(300)
        )
    ).all()
    marketing_by_id = {str(a.id): a for a in marketing}
    medical_by_id = {str(v.id): v for v in visits}
    pharmacy_by_id = {str(v.id): v for v in pdv_visits}
    doctor_names = {str(d.id): d.full_name for _, d in panels}
    site_names = {str(s.id): s.name for s in sites}
    pharmacy_names = {
        str(p.id): site_names.get(str(p.institution_id), "Droguería") for p in pharmacies
    }
    plan_rows = []
    for plan in plans:
        row = row_json(plan)
        # Published routes are plans, not a second visit ledger. Read the current
        # execution state from the same Visit records used by the original app.
        if plan.status == "published":
            row["stops"] = []
            for stop in plan.stops:
                if stop["kind"] == "marketing":
                    item = dict(stop)
                    activity = marketing_by_id.get(stop.get("target_id"))
                    if activity:
                        item.update(
                            status=activity.status,
                            locked=activity.status in ("in_progress", "completed"),
                            scheduled_at=activity.starts_at.isoformat(),
                            actual_arrived_at=activity.started_at.isoformat()
                            if activity.started_at
                            else None,
                            actual_finished_at=activity.completed_at.isoformat()
                            if activity.completed_at
                            else None,
                            rescheduled=activity.status in ("cancelled", "draft")
                            or activity.starts_at.isoformat() != stop.get("arrival_at"),
                        )
                    row["stops"].append(item)
                    continue
                live = (medical_by_id if stop["kind"] == "doctor" else pharmacy_by_id).get(
                    stop.get("visit_id")
                )
                item = dict(stop)
                if live:
                    item.update(
                        status=live.status,
                        locked=live.status not in {"scheduled", "not_done"},
                        actual_arrived_at=live.arrived_at.isoformat() if live.arrived_at else None,
                        actual_finished_at=live.finished_at.isoformat()
                        if live.finished_at
                        else None,
                        scheduled_at=live.scheduled_at.isoformat(),
                        rescheduled=live.scheduled_at.astimezone(ZONE).date() != plan.day,
                    )
                row["stops"].append(item)
        plan_rows.append(row)
    agenda = [
        {
            "id": str(v.id),
            "kind": "doctor",
            "target_id": str(v.doctor_id),
            "label": doctor_names.get(str(v.doctor_id), "Visita médica"),
            "scheduled_at": v.scheduled_at.isoformat(),
            "status": v.status,
            "planned_by": v.planned_by,
            "href": f"/visitas/{v.id}",
        }
        for v in visits
        if not (
            v.status == "not_done"
            and v.planned_by == "routing"
            and v.not_done_reason == "rescheduled"
        )
    ] + [
        {
            "id": str(v.id),
            "kind": "pharmacy",
            "target_id": str(v.pharmacy_id),
            "label": pharmacy_names.get(str(v.pharmacy_id), "Droguería"),
            "scheduled_at": v.scheduled_at.isoformat(),
            "status": v.status,
            "planned_by": v.planned_by,
            "href": None,
        }
        for v in pdv_visits
        if not (v.status == "not_done" and (v.report or {}).get("replanned"))
    ]
    agenda += [
        {
            "id": str(a.id),
            "kind": "marketing",
            "target_id": str(a.id),
            "label": KINDS[a.kind] + " · " + site_names.get(str(a.institution_id), "Institución"),
            "scheduled_at": a.starts_at.isoformat(),
            "status": a.status,
            "planned_by": "rep",
            "href": "/territorio/?module=marketing&activity=" + str(a.id),
        }
        for a in marketing
        if a.status != "cancelled"
    ]
    return {
        "user": {
            "id": str(actor.id),
            "name": actor.full_name,
            "role": actor.role,
            "management_profile": actor.management_profile,
            "capabilities": capabilities(actor),
        },
        "representative_id": str(rep_id),
        "can_manage": permits(actor, "territory.manage"),
        "can_edit": permits(actor, "territory.write"),
        "can_supervise": actor.role in MANAGERS,
        "representatives": [{"id": str(x.id), "name": x.full_name} for x in reps],
        "contacts": [row_json(c) for c in contacts],
        "availability": [
            row_json(a)
            for a in (
                await session.execute(
                    select(ReceptionAvailability).where(
                        ReceptionAvailability.doctor_id.in_([d.id for p, d in panels])
                    )
                )
            )
            .scalars()
            .all()
        ],
        "doctors": [
            {
                "id": str(d.id),
                "name": d.full_name,
                "specialty": d.specialty,
                "institution_id": str(d.institution_id) if d.institution_id else None,
                "line_id": str(p.default_line_id) if p.default_line_id else None,
            }
            for p, d in panels
        ],
        "sites": [
            {
                "id": str(s.id),
                "name": s.name,
                "address": s.address,
                "city": s.city,
                "lat": s.lat,
                "lng": s.lng,
            }
            for s in sites
        ],
        "locations": [row_json(x) for x in geo],
        "potentials": [{**row_json(x), "summary": potential_summary(x.data)} for x in potentials],
        "pharmacies": [row_json(x) for x in pharmacies if not x.data.get("merged_into")],
        "pharmacy_visits": [row_json(x) for x in pdv_visits],
        "referrals": [row_json(x) for x in referrals],
        "requirements": [row_json(x) for x in rules],
        "visits": [
            {
                "id": str(v.id),
                "doctor_id": str(v.doctor_id),
                "scheduled_at": v.scheduled_at.isoformat(),
                "status": v.status,
            }
            for v in visits
        ],
        "products": [
            {"id": str(x.id), "name": x.name, "line_id": str(x.line_id)}
            for x in (
                await session.execute(
                    select(Product).where(
                        Product.active.is_(True),
                        Product.line_id.in_(line_ids(actor))
                        if line_ids(actor) is not None
                        else True,
                    )
                )
            ).scalars()
        ],
        "presentations": [
            row_json(x)
            for x in (
                await session.scalars(
                    select(ProductPresentation)
                    .join(Product)
                    .where(
                        ProductPresentation.active.is_(True),
                        Product.line_id.in_(line_ids(actor))
                        if line_ids(actor) is not None
                        else True,
                    )
                    .order_by(ProductPresentation.name)
                )
            ).all()
        ],
        "cycles": [
            row_json(x)
            for x in (
                await session.scalars(
                    select(CommercialCycle)
                    .where(
                        CommercialCycle.active.is_(True),
                        CommercialCycle.line_id.in_(line_ids(actor))
                        if line_ids(actor) is not None
                        else True,
                    )
                    .order_by(CommercialCycle.starts_on)
                )
            ).all()
        ],
        "policy": row_json(policy) if policy else None,
        "plans": plan_rows,
        "agenda": sorted(agenda, key=lambda v: v["scheduled_at"]),
        "jobs": [row_json(x) for x in jobs],
        "server_time": clock.now().isoformat(),
    }


async def enqueue(session, rep, day, key, max_contacts=12):
    existing = (
        await session.execute(select(RouteJob).where(RouteJob.key == key))
    ).scalar_one_or_none()
    if existing:
        return existing
    job = RouteJob(
        id=uuid7(),
        key=key,
        representative_id=rep,
        day=day,
        max_contacts=max_contacts,
        next_attempt=clock.now(),
        created_at=clock.now(),
    )
    session.add(job)
    await session.flush()
    return job


async def validate_products(session, ids):
    ids = set(ids)
    rows = (
        (
            await session.execute(
                select(Product.id).where(Product.id.in_(ids), Product.active.is_(True))
            )
        )
        .scalars()
        .all()
        if ids
        else []
    )
    if len(rows) != len(ids):
        raise ApiError(422, "unknown_product", "Selecciona productos activos del catálogo")


async def execute(session: AsyncSession, actor: User, command: Command, ctx):
    require_capability(
        actor,
        "knowledge.manage"
        if command.type.startswith("knowledge.")
        else "marketing.write"
        if command.type.startswith("marketing.")
        else "territory.write",
    )
    fingerprint = hashlib.sha256(
        json.dumps(command.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    # La reserva global de secuencia serializa comandos también entre procesos.
    seq = await next_change_seq(session)
    previous = await session.get(TerritoryCommand, command.id)
    if previous:
        if previous.actor_id != actor.id or previous.fingerprint != fingerprint:
            raise ApiError(
                409, "idempotency_conflict", "Este identificador ya corresponde a otra operación"
            )
        response = previous.response
        await session.rollback()
        return response
    result = await dispatch(session, actor, command, ctx, seq)
    if command.type in {
        "location.verify",
        "potential.save",
        "availability.save",
        "pharmacy.save",
        "pharmacy.visit.schedule",
        "requirement.save",
        "policy.save",
    }:
        from .planning import minute, next_working_day, working_day

        # Recalcular con cambios de insumos. La clave del comando evita trabajos duplicados.
        policies = (
            (await session.execute(select(RoutePolicy).where(RoutePolicy.active.is_(True))))
            .scalars()
            .all()
        )
        today = clock.now().astimezone(ZONE).date()
        for policy in policies:
            if (
                actor.role not in MANAGERS
                and command.type != "location.verify"
                and policy.representative_id != actor.id
            ):
                continue
            for day in [today, next_working_day(policy.data, today)]:
                if working_day(policy.data, day) and (
                    day > today
                    or minute(clock.now().astimezone(ZONE)) < minute(policy.data["ends"])
                ):
                    await enqueue(
                        session,
                        policy.representative_id,
                        day,
                        f"change:{command.id}:{policy.representative_id}:{day}",
                    )
    session.add(
        TerritoryCommand(
            id=command.id,
            actor_id=actor.id,
            fingerprint=fingerprint,
            response=result,
            created_at=clock.now(),
        )
    )
    await session.commit()
    return result


async def dispatch(session, actor, command, ctx, seq):
    kind = command.type
    if kind.startswith("learning."):
        from uno.modules.workflows.learning import command as learning_command
        return await learning_command(session, actor, command)
    if kind == "commercial.confirm":
        from uno.modules.marketing.commercial import confirm
        return await confirm(session, actor, command)
    payload = command.payload
    expected = command.expected_version
    now = clock.now()
    if kind == "marketing.save":
        from uno.modules.marketing.service import save_activity

        return await save_activity(session, actor, command)
    if kind == "location.verify":
        p = VerifyLocation.model_validate(payload)
        site = await site_access(session, actor, p.institution_id)
        if not bogota_point(p.lat, p.lng):
            raise ApiError(
                422,
                "outside_pilot",
                "El punto está fuera del área de trabajo de Bogotá; revisa la dirección",
            )
        if p.source == "gps" and (p.accuracy_m is None or p.accuracy_m > 100):
            raise ApiError(
                422,
                "imprecise_gps",
                "Para verificar con GPS se necesita una precisión de 100 m o mejor",
            )
        row = await session.get(LocationVerification, site.id)
        version(row, expected)
        evidence = {
            "previous": {"lat": site.lat, "lng": site.lng},
            "point": {"lat": p.lat, "lng": p.lng},
            "accuracy_m": p.accuracy_m,
            "note": p.note,
        }
        if row:
            row.version += 1
            row.source = p.source
            row.status = "verified"
            row.evidence = evidence
            row.updated_by = actor.id
            row.updated_at = now
        else:
            row = LocationVerification(
                institution_id=site.id,
                source=p.source,
                status="verified",
                version=1,
                evidence=evidence,
                updated_by=actor.id,
                updated_at=now,
            )
            session.add(row)
        site.lat, site.lng, site.ref_source, site.change_seq = p.lat, p.lng, "verified", seq
        await audit(session, actor, "location_verified", site.id, row.version)
        return {"id": str(site.id), "version": row.version}
    if kind == "availability.save":
        p = AvailabilityInput.model_validate(payload)
        await doctor_site_access(session, actor, p.doctor_id, p.institution_id)
        if p.observed_on > now.astimezone(ZONE).date():
            raise ApiError(422, "future_observation", "La confirmación no puede estar en el futuro")
        row = await session.get(ReceptionAvailability, (p.doctor_id, p.institution_id))
        version(row, expected)
        if not row:
            row = ReceptionAvailability(
                doctor_id=p.doctor_id, institution_id=p.institution_id, version=0
            )
            session.add(row)
        row.data = p.model_dump(mode="json", exclude={"doctor_id", "institution_id"})
        row.version += 1
        row.updated_by, row.updated_at = actor.id, now
        await audit(session, actor, "reception_confirmed", p.doctor_id, row.version)
        return {"id": str(p.doctor_id), "version": row.version}
    if kind == "potential.save":
        p = PotentialInput.model_validate(payload)
        await doctor_site_access(session, actor, p.doctor_id, p.institution_id)
        if p.observed_on > now.astimezone(ZONE).date():
            raise ApiError(
                422, "future_observation", "La fecha de observación no puede estar en el futuro"
            )
        row = await session.get(MedicalPotential, (p.doctor_id, p.institution_id))
        version(row, expected)
        data = p.model_dump(mode="json", exclude={"doctor_id", "institution_id"})
        if row:
            row.version += 1
            row.data = data
            row.updated_by = actor.id
            row.updated_at = now
        else:
            row = MedicalPotential(
                doctor_id=p.doctor_id,
                institution_id=p.institution_id,
                data=data,
                version=1,
                updated_by=actor.id,
                updated_at=now,
            )
            session.add(row)
        await audit(session, actor, "potential_updated", p.doctor_id, row.version)
        return {"id": str(p.doctor_id), "version": row.version, "summary": potential_summary(data)}
    if kind == "pharmacy.save":
        p = PharmacyInput.model_validate(payload)
        row = await session.get(Pharmacy, p.id)
        version(row, expected)
        rep = p.representative_id or (row.representative_id if row else actor.id)
        owner(actor, rep)
        rep_user = await session.get(User, rep)
        if not rep_user or not rep_user.is_active or rep_user.role != "rep":
            raise ApiError(422, "invalid_representative", "Selecciona un visitador activo")
        if row:
            owner(actor, row.representative_id)
            site = await session.get(Institution, row.institution_id)
            if site.address != p.address or site.city != p.city:
                geo = await session.get(LocationVerification, site.id)
                if geo:
                    geo.status = "needs_review"
                    geo.version += 1
                site.lat = None
                site.lng = None
            site.name = p.name
            site.address = p.address
            site.city = p.city
            site.change_seq = seq
            row.version += 1
        else:
            site = Institution(
                id=uuid7(),
                name=p.name,
                address=p.address,
                city=p.city,
                created_by=actor.id,
                created_at=now,
                change_seq=seq,
            )
            session.add(site)
            await session.flush()
            row = Pharmacy(
                id=p.id, institution_id=site.id, representative_id=rep, version=1, updated_at=now
            )
            session.add(row)
        row.representative_id = rep
        row.chain = p.chain
        row.active = p.active
        row.updated_at = now
        row.data = p.model_dump(mode="json", include={"contact", "phone", "reception"})
        await audit(session, actor, "pharmacy_updated", row.id, row.version)
        return {"id": str(row.id), "institution_id": str(site.id), "version": row.version}
    if kind == "pharmacy.visit.schedule":
        p = SchedulePharmacy.model_validate(payload)
        item = await pharmacy_access(session, actor, p.pharmacy_id)
        if not item.active:
            raise ApiError(422, "inactive_pharmacy", "Esta droguería está inactiva")
        row = await session.get(PharmacyVisit, p.id)
        version(row, expected)
        if row and row.status != "scheduled":
            raise ApiError(409, "visit_started", "No se puede mover una visita iniciada")
        if row and row.pharmacy_id != item.id:
            raise ApiError(409, "target_changed", "No se puede cambiar el destino de una visita")
        if row:
            row.scheduled_at = p.scheduled_at
            row.version += 1
            row.updated_at = now
        else:
            row = PharmacyVisit(
                id=p.id,
                pharmacy_id=item.id,
                representative_id=item.representative_id,
                scheduled_at=p.scheduled_at,
                updated_at=now,
                version=1,
            )
            session.add(row)
        await audit(session, actor, "pharmacy_visit_scheduled", row.id, row.version)
        return {"id": str(row.id), "version": row.version}
    if kind in {"pharmacy.visit.arrive", "pharmacy.visit.finish", "pharmacy.visit.not_done"}:
        p = VisitAction.model_validate(payload)
        row = await session.get(PharmacyVisit, p.id)
        if not row:
            raise ApiError(404, "not_found", "No se encontró la visita")
        owner(actor, row.representative_id)
        version(row, expected)
        if p.occurred_at > now + timedelta(
            minutes=5
        ) or p.occurred_at < row.scheduled_at - timedelta(days=7):
            raise ApiError(422, "invalid_time", "Revisa la fecha del dispositivo")
        action = kind.rsplit(".", 1)[-1]
        allowed = {
            "arrive": {"scheduled"},
            "finish": {"in_progress"},
            "not_done": {"scheduled", "in_progress"},
        }
        if row.status not in allowed[action]:
            raise ApiError(
                409, "invalid_transition", "Esta acción no corresponde al estado de la visita"
            )
        if action == "finish" and p.occurred_at < row.arrived_at:
            raise ApiError(422, "invalid_time", "La salida no puede ser anterior a la llegada")
        if action == "not_done" and not p.reason.strip():
            raise ApiError(422, "reason_required", "Indica por qué no se realizó")
        row.status = {"arrive": "in_progress", "finish": "finished", "not_done": "not_done"}[action]
        if action == "arrive":
            row.arrived_at = p.occurred_at
        if action == "finish":
            row.finished_at = p.occurred_at
        from uno.modules.agenda.geofence import Reading, Reference, classify

        pharmacy = await session.get(Pharmacy, row.pharmacy_id)
        site = await session.get(Institution, pharmacy.institution_id)
        geo = await session.get(LocationVerification, site.id)
        reference = (
            Reference(site.lat, site.lng)
            if geo and geo.status == "verified" and site.lat is not None and site.lng is not None
            else None
        )
        reading = Reading(p.point.lat, p.point.lng, p.accuracy_m) if p.point else None
        geo_state, distance = classify(reading, reference, site.radius_m)
        row.location = {
            **row.location,
            action: {
                **p.model_dump(mode="json", exclude={"id"}),
                "geo_state": geo_state,
                "distance_m": distance,
            },
        }
        row.version += 1
        row.updated_at = now
        await audit(session, actor, "pharmacy_visit_" + action, row.id, row.version)
        policy = await session.get(RoutePolicy, row.representative_id)
        if policy and policy.active:
            await enqueue(
                session, row.representative_id, now.astimezone(ZONE).date(), f"field:{command.id}"
            )
        return {"id": str(row.id), "version": row.version, "status": row.status}
    if kind == "pharmacy.visit.report":
        p = PharmacyReport.model_validate(payload)
        row = await session.get(PharmacyVisit, p.id)
        if not row:
            raise ApiError(404, "not_found", "No se encontró la visita")
        owner(actor, row.representative_id)
        version(row, expected)
        if row.status not in {"finished", "confirmed"}:
            raise ApiError(
                409, "visit_not_finished", "Termina la visita antes de confirmar su reporte"
            )
        await validate_products(
            session, [x.product_id for x in p.observations] + [x.product_id for x in p.commercial]
        )
        if len({x.product_id for x in p.observations}) != len(p.observations):
            raise ApiError(422, "duplicate_product", "Registra una observación por producto")
        row.report = {
            **p.model_dump(mode="json", exclude={"id"}),
            "confirmed_by": str(actor.id),
            "confirmed_at": now.isoformat(),
        }
        row.status = "confirmed"
        row.version += 1
        row.updated_at = now
        await audit(session, actor, "pharmacy_report_confirmed", row.id, row.version)
        return {"id": str(row.id), "version": row.version}
    if kind == "referral.create":
        p = ReferralInput.model_validate(payload)
        visit = await session.get(Visit, p.visit_id)
        if not visit:
            raise ApiError(404, "not_found", "No se encontró la visita médica")
        owner(actor, visit.representative_id)
        if visit.status not in {"finished", "confirmed"}:
            raise ApiError(
                422,
                "visit_not_finished",
                "El direccionamiento debe relacionarse con una visita realizada",
            )
        pharmacy = await pharmacy_access(session, actor, p.pharmacy_id)
        if pharmacy.representative_id != visit.representative_id:
            raise ApiError(
                422,
                "territory_mismatch",
                "La droguería y la visita deben pertenecer al mismo territorio",
            )
        await validate_products(session, p.product_ids)
        if await session.get(PharmacyReferral, p.id):
            raise ApiError(409, "duplicate_referral", "El direccionamiento ya existe")
        session.add(
            PharmacyReferral(
                id=p.id,
                visit_id=p.visit_id,
                pharmacy_id=p.pharmacy_id,
                representative_id=visit.representative_id,
                products=[str(x) for x in p.product_ids],
                note=p.note,
                created_at=now,
            )
        )
        await audit(session, actor, "pharmacy_referral_created", p.id)
        return {"id": str(p.id), "version": 1}
    if kind == "policy.save":
        management(actor)
        p = PolicyInput.model_validate(payload)
        rep = await session.get(User, p.representative_id)
        if not rep or not rep.is_active or rep.role != "rep":
            raise ApiError(422, "invalid_representative", "Selecciona un visitador activo")
        if not bogota_point(p.origin.lat, p.origin.lng):
            raise ApiError(422, "outside_pilot", "Revisa el punto de inicio en Bogotá")
        row = await session.get(RoutePolicy, p.representative_id)
        version(row, expected)
        data = p.model_dump(mode="json", exclude={"representative_id", "active"})
        if row:
            row.version += 1
            row.data = data
            row.active = p.active
            row.approved_by = actor.id
            row.updated_at = now
        else:
            row = RoutePolicy(
                representative_id=p.representative_id,
                data=data,
                active=p.active,
                approved_by=actor.id,
                updated_at=now,
                version=1,
            )
            session.add(row)
        await audit(session, actor, "route_policy_approved", p.representative_id, row.version)
        return {"id": str(p.representative_id), "version": row.version}
    if kind == "requirement.save":
        management(actor)
        p = RequirementInput.model_validate(payload)
        if p.doctor_id:
            await doctor_access(session, actor, p.doctor_id, p.representative_id)
            if p.institution_id:
                await doctor_site_access(
                    session, actor, p.doctor_id, p.institution_id, p.representative_id
                )
        else:
            pharmacy = await pharmacy_access(session, actor, p.pharmacy_id)
            if pharmacy.representative_id != p.representative_id:
                raise ApiError(
                    422, "territory_mismatch", "La droguería no corresponde al visitador"
                )
        await validate_products(session, p.product_sequence)
        row = await session.get(VisitRequirement, p.id)
        version(row, expected)
        if row and row.representative_id != p.representative_id:
            raise ApiError(
                409, "owner_changed", "No se puede cambiar el propietario de una regla existente"
            )
        overlaps = (
            await session.execute(
                select(VisitRequirement).where(
                    VisitRequirement.id != p.id,
                    VisitRequirement.representative_id == p.representative_id,
                    VisitRequirement.active.is_(True),
                    VisitRequirement.cycle_start <= p.cycle_end,
                    VisitRequirement.cycle_end >= p.cycle_start,
                    VisitRequirement.doctor_id == p.doctor_id,
                    VisitRequirement.pharmacy_id == p.pharmacy_id,
                    or_(
                        VisitRequirement.institution_id == p.institution_id,
                        VisitRequirement.institution_id.is_(None),
                    )
                    if p.institution_id
                    else True,
                )
            )
        ).first()
        if overlaps and p.active:
            raise ApiError(
                409,
                "overlapping_cycle",
                "Ya hay una regla activa para este destino en un ciclo superpuesto",
            )
        if not row:
            row = VisitRequirement(
                id=p.id, representative_id=p.representative_id, version=0, updated_at=now
            )
            session.add(row)
        row.doctor_id = p.doctor_id
        row.institution_id = p.institution_id
        row.pharmacy_id = p.pharmacy_id
        row.cycle_start = p.cycle_start
        row.cycle_end = p.cycle_end
        row.active = p.active
        row.data = {
            **(row.data or {}),
            **p.model_dump(
                mode="json",
                include={
                    "windows",
                    "min_gap_days",
                    "product_sequence",
                    "service_minutes",
                    "priority",
                },
            ),
        }
        row.version += 1
        row.updated_at = now
        await audit(session, actor, "visit_requirement_updated", row.id, row.version)
        return {"id": str(row.id), "version": row.version}
    if kind == "route.generate":
        management(actor)
        p = GenerateInput.model_validate(payload)
        if p.day < now.astimezone(ZONE).date():
            raise ApiError(422, "past_route", "No se pueden construir rutas en el pasado")
        policy = await session.get(RoutePolicy, p.representative_id)
        if not policy:
            raise ApiError(
                422, "missing_policy", "Configura primero la jornada y el punto de inicio"
            )
        job = await enqueue(
            session, p.representative_id, p.day, f"manual:{command.id}", p.max_contacts
        )
        return {"id": str(job.id), "status": "queued"}
    if kind == "route.publish":
        management(actor)
        p = PublishInput.model_validate(payload)
        from .planning import publish

        return await publish(session, actor, p.id, expected, p.reason)
    if kind == "task.update":
        from uno.modules.workflows.tasks import update_task

        return await update_task(session, actor, command)
    if kind == "route.incident":
        from uno.modules.workflows.execution import incident

        return await incident(session, actor, command)
    if kind.startswith("knowledge."):
        from uno.modules.workflows.knowledge import review_command

        return await review_command(session, actor, command)
    raise ApiError(422, "unknown_command", "Operación no reconocida")
