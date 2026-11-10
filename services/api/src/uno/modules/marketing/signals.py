"""Explainable quality signals and a deliberately conservative operational baseline.

No prescriptions, sales or clinical judgments are inferred from activity counts.
"""
from collections import Counter, defaultdict
from datetime import timedelta
from statistics import mean, median, pstdev
from uno.modules.territory.service import ZONE


def signals(visits, reports, now, *, demo=False):
    findings = []
    finished = [v for v in visits if v.finished_at and v.status != "not_done"]
    durations = [(v, (v.finished_at-v.arrived_at).total_seconds()/60) for v in finished
                 if v.arrived_at and v.finished_at >= v.arrived_at]
    def add(v, code, title, detail):
        findings.append({"visit_id":str(v.id), "code":code, "title":title, "detail":detail,
                         "href":"/territorio/?report="+str(v.id), "method":"regla verificable"})
    for v in visits:
        if v.arrived_at and v.arrival_geo_state in ("lejos", "sin_gps", "imprecisa", "sin_referencia"):
            add(v, "location", "Llegada sin ubicación verificada", "Revisa la evidencia de ubicación; no implica una falta del visitador.")
        if v.finished_at and now-v.finished_at > timedelta(hours=24) and (v.id not in reports or reports[v.id].status != "confirmed"):
            add(v, "pending_report", "Reporte pendiente por más de 24 horas", "La visita terminó y todavía falta confirmar su resultado.")
    grouped = defaultdict(list)
    for v in finished:
        if v.arrived_at: grouped[v.representative_id].append(v)
    for rows in grouped.values():
        rows.sort(key=lambda v:v.arrived_at)
        latest_end = None
        for v in rows:
            if latest_end and v.arrived_at < latest_end:
                add(v, "overlap", "Horarios de visita superpuestos", "Contrasta las horas registradas de llegada y salida.")
            latest_end = max(latest_end, v.finished_at) if latest_end else v.finished_at
    if len(durations) >= 8:
        center = median(t for _, t in durations)
        mad = median(abs(t-center) for _, t in durations)
        threshold = max(15, 3*1.4826*mad)
        for v, value in durations:
            if abs(value-center) > threshold:
                add(v, "duration", "Duración atípica frente al grupo", f"{value:.0f} min; mediana {center:.0f} min. Señal para revisión, no evaluación automática.")
                findings[-1]["method"] = "mediana y desviación absoluta (MAD)"
    days = Counter(v.finished_at.astimezone(ZONE).date() for v in finished)
    today = now.astimezone(ZONE).date()
    historical = []
    if days:
        d = min(days)
        while d < today:
            if d.weekday()<5: historical.append(days.get(d, 0))
            d += timedelta(days=1)
    baseline = {"status":"insufficient_data", "method":"Media móvil de ejecución; no predice ventas ni prescripción",
                "observed_weekdays":len(historical), "completed_visits":len(finished),
                "required_weekdays":10, "required_visits":20,
                "note":"Se requieren 10 días de lunes a viernes cerrados y 20 visitas terminadas. No se consideran festivos en esta referencia estadística; no agenda visitas."}
    if not demo and len(historical)>=10 and sum(historical)>=20:
        recent=historical[-10:]; average=mean(recent); spread=pstdev(recent)
        errors=[abs(mean(historical[i-5:i])-historical[i]) for i in range(max(5,len(historical)-5),len(historical))]
        baseline.update(status="baseline", expected_per_weekday=round(average,1),
                        observed_range=[round(max(0,average-2*spread),1),round(average+2*spread,1)],
                        backtest_mae=round(mean(errors),1), backtest_days=len(errors),
                        note="Referencia de capacidad del equipo basada en los últimos 10 días hábiles de la muestra. El rango refleja variabilidad observada, no una garantía ni un intervalo calibrado.")
    if demo: baseline.update(status="demo_excluded",note="La demostración no entrena modelos ni altera las métricas del piloto.")
    priority = {"overlap":0,"location":1,"duration":2,"pending_report":3}
    findings.sort(key=lambda row:priority[row["code"]])
    return {"findings":findings[:40], "total_findings":len(findings), "baseline":baseline,
            "durations":[{"visit_id":str(v.id),"minutes":round(t,1)} for v,t in durations[-40:]],
            "definition":"Alertas explicables para revisión humana. No prueban fraude ni miden desempeño clínico."}
