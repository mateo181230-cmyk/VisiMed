"""Explicit, idempotent pilot import. No overwriting of field edits on a rerun."""

from __future__ import annotations

import uuid
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta

from sqlalchemy import select

from uno import clock
from uno.db import next_change_seq
from uno.modules.auth.models import User
from uno.modules.catalog.models import Doctor, Institution, Panel, ProductLine

from .models import (
    LocationVerification,
    PanelContact,
    Pharmacy,
    ReceptionAvailability,
    RoutePolicy,
    VisitRequirement,
)
from .schemas import AvailabilityInput, PolicyInput, RequirementInput
from .service import audit, enqueue


def unique_pharmacies(items):
    """Repeated Pharmadvisor impact codes are aliases, not extra establishments."""
    groups = {}
    for item in items:
        code = item["data"]["external_contact_id"]
        key = (
            item["representative_id"],
            code.split("-")[0],
            item["site"]["city"].strip().upper(),
            item["site"]["address"].strip().upper(),
        )
        groups.setdefault(key, []).append(item)
    result = []
    for group in groups.values():
        group.sort(key=lambda x: (int(x["data"]["external_contact_id"].split("-")[-1]), x["id"]))
        first = deepcopy(group[0])
        for item in group[1:]:
            for key in ("fz", "reception", "additional_reception"):
                assert item["data"].get(key) == first["data"].get(key), (
                    "Conflicting pharmacy aliases"
                )
            assert item["chain"] == first["chain"] and item["active"] == first["active"]
        first["data"]["source_contacts"] = [
            {"id": x["id"], "external_contact_id": x["data"]["external_contact_id"]} for x in group
        ]
        result.append(first)
    return result


async def import_panel(session, bundle, manager_id, *, activate=True, provisional=False):
    """Caller owns the transaction; a failed validation rolls back the whole batch."""
    assert bundle["schema"] == 1
    manager = await session.get(User, manager_id)
    assert manager and manager.is_active and manager.role in {"admin", "manager"}
    line = (
        await session.execute(select(ProductLine).where(ProductLine.code == "SNC"))
    ).scalar_one()
    reps = {uuid.UUID(x) for x in bundle["representatives"].values()}
    for rep_id in reps:
        rep = await session.get(User, rep_id)
        assert rep and rep.is_active and rep.role == "rep", "Invalid pilot representative"
    counts = Counter()
    now = clock.now()
    change = await next_change_seq(session)

    async def site(item):
        sid = uuid.UUID(item["institution_id"])
        row = await session.get(Institution, sid)
        if not row:
            row = Institution(
                id=sid,
                **item["site"],
                ref_source="panel_import",
                created_by=manager_id,
                created_at=now,
                change_seq=change,
            )
            session.add(row)
            await session.flush()
            counts["sites_created"] += 1
        if not await session.get(LocationVerification, sid):
            geo = item["geo"]
            verified = geo["status"] == "exact"
            # A road-access check must also pass before production activation.
            road = geo.get("road")
            if activate:
                verified = verified and bool(road and road.get("distance_m", 99999) <= 200)
            session.add(
                LocationVerification(
                    institution_id=sid,
                    status="verified" if verified else "pending",
                    source="ideca",
                    evidence={**geo["evidence"], "road": road},
                    updated_by=manager_id,
                    updated_at=now,
                )
            )
            counts["verified_sites"] += verified
        return sid

    async def requirement(data, *, rid, rep, doctor=None, sid=None, pharmacy=None, active=True):
        rule_id = uuid.UUID(rid)
        if await session.get(VisitRequirement, rule_id):
            return
        validated = RequirementInput(
            id=rule_id,
            representative_id=rep,
            doctor_id=doctor,
            institution_id=sid,
            pharmacy_id=pharmacy,
            cycle_start=data["cycle_start"],
            cycle_end=data["cycle_end"],
            **{
                k: v
                for k, v in data["data"].items()
                if k
                in {"windows", "min_gap_days", "service_minutes", "priority", "product_sequence"}
            },
            active=active,
        )
        session.add(
            VisitRequirement(
                id=rule_id,
                representative_id=rep,
                doctor_id=doctor,
                institution_id=sid,
                pharmacy_id=pharmacy,
                cycle_start=validated.cycle_start,
                cycle_end=validated.cycle_end,
                data=data["data"],
                active=active,
                updated_at=now,
            )
        )
        counts["rules_created"] += 1

    for item in bundle["records"]:
        rep = uuid.UUID(item["representative_id"])
        assert rep in reps
        doc_id = uuid.UUID(item["doctor_id"])
        cid = uuid.UUID(item["contact_id"])
        if await session.get(PanelContact, cid):
            counts["contacts_preserved"] += 1
            continue
        sid = await site(item)
        doc = await session.get(Doctor, doc_id)
        if not doc:
            doc = Doctor(
                id=doc_id,
                **item["doctor"],
                institution_id=sid,
                review_state="approved",
                created_by=manager_id,
                created_at=now,
                change_seq=change,
            )
            session.add(doc)
            await session.flush()
            counts["doctors_created"] += 1
        if not await session.get(Panel, (rep, doc_id)):
            session.add(
                Panel(
                    representative_id=rep,
                    doctor_id=doc_id,
                    default_line_id=line.id,
                    change_seq=change,
                )
            )
        session.add(
            PanelContact(
                id=cid,
                representative_id=rep,
                doctor_id=doc_id,
                institution_id=sid,
                source_key=item["source_key"],
                data=item["data"],
                active=item["active"],
                updated_at=now,
            )
        )
        counts["contacts_created"] += 1
        if item["availability"] and not await session.get(ReceptionAvailability, (doc_id, sid)):
            value = AvailabilityInput(doctor_id=doc_id, institution_id=sid, **item["availability"])
            session.add(
                ReceptionAvailability(
                    doctor_id=doc_id,
                    institution_id=sid,
                    data=value.model_dump(mode="json", exclude={"doctor_id", "institution_id"}),
                    updated_by=manager_id,
                    updated_at=now,
                )
            )
            counts["hours_created"] += 1
        for rule in item["rules"]:
            await requirement(
                rule, rid=rule["id"], rep=rep, doctor=doc_id, sid=sid, active=item["active"]
            )

    for item in unique_pharmacies(bundle.get("pharmacies", [])):
        pid = uuid.UUID(item["id"])
        rep = uuid.UUID(item["representative_id"])
        assert rep in reps
        if await session.get(Pharmacy, pid):
            counts["pharmacies_preserved"] += 1
            continue
        sid = await site(item)
        session.add(
            Pharmacy(
                id=pid,
                institution_id=sid,
                representative_id=rep,
                chain=item["chain"],
                data=item["data"],
                active=item["active"],
                updated_at=now,
            )
        )
        await session.flush()
        counts["pharmacies_created"] += 1
        for start, end in [("2026-10-14", "2026-11-11"), ("2026-11-12", "2026-12-11")]:
            a, b = date.fromisoformat(start), date.fromisoformat(end)
            n = item["data"]["fz"]
            total = (b - a).days + 1
            windows = [
                {
                    "start": (a + timedelta(days=total * i // n)).isoformat(),
                    "end": (a + timedelta(days=total * (i + 1) // n - 1)).isoformat(),
                }
                for i in range(n)
            ]
            data = {
                "cycle_start": start,
                "cycle_end": end,
                "data": {
                    "windows": windows,
                    "min_gap_days": 6,
                    "service_minutes": 20,
                    "priority": 2,
                    "product_sequence": [],
                    "source": item["data"]["source"],
                    "fz": n,
                    "external_contact_id": item["data"]["external_contact_id"],
                },
            }
            await requirement(
                data,
                rid=str(uuid.uuid5(pid, "rule:" + start)),
                rep=rep,
                pharmacy=pid,
                active=item["active"],
            )

    await session.flush()
    for rep in reps:
        policy = await session.get(RoutePolicy, rep)
        # On repeat imports retain a manager's policy edits and activation choice.
        if counts["contacts_created"] and (not policy or not policy.data.get("panel_import_hash")):
            raw = PolicyInput(
                representative_id=rep,
                active=activate,
                publish_automatically=True,
                origin={"lat": 4.6579746, "lng": -74.0603249},
                origin_label="Novamed · Calle 72 No. 12-65, Chapinero",
                starts_on="2026-10-16",
                ends_on="2026-11-13",
                excluded_dates=["2026-11-02"],
                allow_unconfirmed_reception=provisional,
            ).model_dump(mode="json")
            raw["panel_import_hash"] = bundle["source_hash"]
            if not policy:
                policy = RoutePolicy(
                    representative_id=rep,
                    approved_by=manager_id,
                    updated_at=now,
                    data=raw,
                    active=activate,
                )
                session.add(policy)
            else:
                policy.data = raw
                policy.active = activate
                policy.approved_by = manager_id
                policy.updated_at = now
                policy.version += 1
            if activate:
                await enqueue(
                    session,
                    rep,
                    date(2026, 10, 16),
                    f"panel-import:{rep}:{bundle['source_hash'][:12]}",
                )
    await audit(session, manager, "territory.panel_imported", manager_id)
    await session.flush()
    return dict(counts)
