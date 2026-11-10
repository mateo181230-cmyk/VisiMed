"""Shared, explicit field metrics. Imported history is not pilot execution."""
from collections import Counter, defaultdict
from datetime import date, datetime, time
from math import ceil

from sqlalchemy import select
from uno import clock

from uno.modules.agenda.models import Visit
from uno.modules.calls.models import Call, CallVisit, VisitReport
from uno.modules.calls.brands import key, catalogue
from uno.modules.calls.snc_report import SNCReport
from uno.modules.territory.models import VisitRequirement, RoutePlan
from uno.modules.territory.service import ZONE


def operational(visit, report=None):
    if getattr(visit, "planned_by", None) == "demo":
        return False
    if report and (report.extractor_version or "").lower().startswith(("import", "synthetic", "qa-")):
        return False
    values = list((report.fields or {}).values()) if report else []
    if values and all(x.get("source") in ("import", "synthetic") for x in values):
        return False
    return True


def percentile(values, q):
    return sorted(values)[max(0, ceil(len(values)*q)-1)] if values else None


async def measures(session, reps, lines, start, end, visits, reports, plans, include_demo=False):
    entries = {key(x["name"]): x["name"] for x in await catalogue(session, lines)}
    products = defaultdict(lambda: Counter(presentations=0, objectives=0, achieved=0, partial=0, not_achieved=0, unknown=0, barriers=0, referred=0))
    barrier_counts = Counter()
    eligible = visits if include_demo else [v for v in visits if operational(v, reports.get(v.id))]
    for v in eligible:
        report = reports.get(v.id)
        if not report or report.status != "confirmed" or not v.finished_at:
            continue
        raw = report.fields.get("snc_report_json", {}).get("value")
        if not raw:
            continue
        try:
            data = SNCReport.model_validate_json(raw)
        except ValueError:
            continue
        referred = {key(n) for r in data.referrals or [] for n in r.products or []}
        for p in data.products:
            name = entries.get(key(p.name))
            if not name:
                continue
            c = products[name]; c["presentations"] += 1
            c["objectives"] += bool(p.objective); c[p.achievement] += 1
            c["barriers"] += bool(p.barriers); c["referred"] += key(p.name) in referred
            for barrier in p.barriers or []:
                barrier_counts[(name, barrier)] += 1
    calls = (await session.scalars(select(Call).join(CallVisit).where(CallVisit.visit_id.in_([v.id for v in eligible]), Call.provider == "elevenlabs"))).unique().all()
    durations = [c.duration_s for c in calls if c.duration_s is not None and c.status == "completed" and not str(c.provider_conversation_id or "").startswith(("synthetic", "qa-"))]
    requirements = (await session.scalars(select(VisitRequirement).where(VisitRequirement.representative_id.in_(reps), VisitRequirement.active.is_(True), VisitRequirement.doctor_id.is_not(None), VisitRequirement.cycle_start<=end, VisitRequirement.cycle_end>=start))).all()
    # Only requirements for doctors/sites actually in the authorized line scope.
    from uno.modules.catalog.models import Panel
    panel = set((await session.execute(select(Panel.representative_id, Panel.doctor_id).where(Panel.representative_id.in_(reps),Panel.default_line_id.in_(lines)))).all())
    requirements = [r for r in requirements if (r.representative_id,r.doctor_id) in panel]
    if include_demo: requirements = []
    target = covered = overdue = gap_violations = 0
    actionable = []
    cutoff = min(end, clock.now().astimezone(ZONE).date())
    if requirements:
        from uno.modules.catalog.models import Doctor, Institution
        doctors = {d.id:d.full_name for d in (await session.scalars(select(Doctor).where(Doctor.id.in_([r.doctor_id for r in requirements])))).all()}
        sites = {s.id:s.name for s in (await session.scalars(select(Institution).where(Institution.id.in_([r.institution_id for r in requirements if r.institution_id])))).all()}
        lower=datetime.combine(min(r.cycle_start for r in requirements),time(),ZONE)
        cycle_visits=(await session.scalars(select(Visit).where(Visit.representative_id.in_(reps),Visit.primary_line_id.in_(lines),Visit.scheduled_at>=lower,Visit.finished_at.is_not(None)))).all()
        cycle_reports={r.visit_id:r for r in (await session.scalars(select(VisitReport).where(VisitReport.visit_id.in_([v.id for v in cycle_visits])))).all()}
        for r in requirements:
            dates=sorted(v.scheduled_at.astimezone(ZONE).date() for v in cycle_visits if v.representative_id==r.representative_id and v.doctor_id==r.doctor_id and (not r.institution_id or v.institution_id==r.institution_id) and v.status!="not_done" and operational(v,cycle_reports.get(v.id)) and r.cycle_start<=v.scheduled_at.astimezone(ZONE).date()<=min(r.cycle_end,cutoff))
            gap_violations+=sum((b-a).days<r.data.get("min_gap_days",6) for a,b in zip(dates,dates[1:]))
            for w in r.data.get("windows",[]):
                a,b=date.fromisoformat(w["start"]),date.fromisoformat(w["end"])
                target+=1; done=any(a<=d<=b for d in dates); covered+=done
                overdue+=not done and b<cutoff
                if not done and b<cutoff:
                    actionable.append({"requirement_id":str(r.id),"representative_id":str(r.representative_id),"doctor":doctors.get(r.doctor_id,"Médico"),"site":sites.get(r.institution_id,"Sede no registrada"),"window_start":str(a),"window_end":str(b),"href":"/territorio/?rep="+str(r.representative_id)+"&day="+str(end)})
    return {
        "version":"snc-kpi-1", "excluded_history":len(visits)-len(eligible),
        "brands":[{"name":n,**c,"achievement_rate":round(100*c["achieved"]/c["presentations"],1)} for n,c in sorted(products.items())],
        "barriers":[{"brand":n,"text":t,"count":c} for (n,t),c in barrier_counts.most_common(15)],
        "voice":{"calls":len(durations),"p50_seconds":percentile(durations,.5),"p95_seconds":percentile(durations,.95),"over_300_seconds":sum(d>300 for d in durations)},
        "frequency":{"required_windows":target,"covered_windows":covered,"overdue_windows":overdue,"gap_violations":gap_violations,"as_of":str(cutoff),"actionable":sorted(actionable,key=lambda r:r["window_end"])[:25]},
        "routes":[{"id":str(p.id),"day":str(p.day),"representative_id":str(p.representative_id),"stops":len(p.stops),"issues":len(p.issues),"has_exception":bool(p.approval),"travel_minutes":p.metrics.get("travel_minutes"),"href":"/territorio/?rep="+str(p.representative_id)+"&day="+str(p.day)} for p in plans],
        "definitions":{
            "brands":"Presentaciones en reportes confirmados de visitas terminadas. Logro = presentaciones con resultado logrado / presentaciones; desconocidos permanecen en el denominador. No mide prescripción.",
            "frequency":"Ventanas FZ por sede en ciclos que cruzan el período. Cubierta = al menos una visita terminada dentro de la ventana hasta la fecha de corte. Mercadeo no cubre FZ. Vencida = fin de ventana anterior al corte sin visita.",
            "voice":"Duración registrada por ElevenLabs, p50 y p95 por rango más cercano. Sin duración se excluye, no se convierte en cero.",
            "provenance":"Historial marcado como importado y pruebas sintéticas se excluyen de ejecución. Los cortes comerciales permanecen separados.",
        },
    }
