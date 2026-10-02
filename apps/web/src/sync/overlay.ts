/**
 * Vista optimista: «lo que ve la pantalla = foto del servidor + eventos locales aún no
 * confirmados aplicados encima» (doc 01 §10.1).
 *
 * Son funciones puras. Cada reductor es **idempotente**: aplicar un evento sobre una foto que ya
 * lo incluye da el mismo resultado. Por eso los eventos confirmados se pueden seguir aplicando
 * hasta que llegue la siguiente bajada de estado, sin parpadeos ni duplicados.
 */
import type {
  DoctorRow,
  GeoResult,
  InstitutionRow,
  OutboxRow,
  ReportRow,
  VisitRow,
} from "../db/db";
import { RADIO_INSTITUCION_M, clasificar } from "../features/geo/geocerca";
import type { GeoEstado } from "../features/geo/tipos";
import type {
  DoctorCreatedPayload,
  ReportFieldEditedPayload,
  VisitLocationRetriedPayload,
  VisitNotDonePayload,
  VisitRescheduledPayload,
  VisitScheduledPayload,
  VisitTouchPayload,
  WireLocation,
} from "./events";

export interface Snapshot {
  visits: VisitRow[];
  doctors: DoctorRow[];
  institutions: InstitutionRow[];
  reports?: ReportRow[];
}

export interface View {
  visits: Map<string, VisitRow>;
  doctors: Map<string, DoctorRow>;
  institutions: Map<string, InstitutionRow>;
  reports: Map<string, ReportRow>;
}

/** Estados de la cola que siguen «vivos» en pantalla (los rechazados y vencidos no). */
export const LIVE_STATUSES: ReadonlySet<string> = new Set([
  "capturing",
  "pending",
  "sending",
  "confirmed",
]);

/** Una ubicación sin lectura o imprecisa se puede volver a tomar (doc 01 §9.3; contrato `visit_location_retried`). */
export const RETRYABLE_GEO: ReadonlySet<GeoEstado> = new Set([
  "sin_gps",
  "imprecisa",
]);

/**
 * Clasifica la ubicación de un toque contra el lugar de la visita (su institución). Es la misma regla que
 * aplica el servidor; el teléfono la calcula ya para mostrar el resultado sin red.
 */
export function geoOf(
  location: WireLocation | null,
  institution: InstitutionRow | undefined,
): GeoResult {
  const reference =
    institution && institution.lat !== null && institution.lng !== null
      ? { lat: institution.lat, lng: institution.lng }
      : null;
  const { estado, distancia_m } = clasificar(
    location,
    reference,
    institution?.radius_m ?? RADIO_INSTITUCION_M,
  );
  return {
    state: estado,
    distance_m: distancia_m,
    precision_m: location?.precision_m ?? null,
  };
}

export function overlay(base: Snapshot, events: OutboxRow[]): View {
  const view: View = {
    visits: new Map(base.visits.map((v) => [v.id, v])),
    doctors: new Map(base.doctors.map((d) => [d.id, d])),
    institutions: new Map(base.institutions.map((i) => [i.id, i])),
    reports: new Map((base.reports ?? []).map((r) => [r.visit_id, r])),
  };
  const ordered = events
    .filter((e) => LIVE_STATUSES.has(e.status))
    .sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0));
  for (const ev of ordered) applyEvent(view, ev);
  return view;
}

export function applyEvent(view: View, ev: OutboxRow): void {
  switch (ev.type) {
    case "doctor_created": {
      const p = ev.payload as unknown as DoctorCreatedPayload;
      let institutionId = p.institution_id ?? null;
      if (p.institution) {
        institutionId = p.institution.id;
        if (!view.institutions.has(p.institution.id)) {
          view.institutions.set(p.institution.id, {
            id: p.institution.id,
            name: p.institution.name,
            address: p.institution.address ?? null,
            city: p.institution.city ?? null,
            lat: null,
            lng: null,
            radius_m: RADIO_INSTITUCION_M,
          });
        }
      }
      if (!view.doctors.has(p.doctor_id)) {
        view.doctors.set(p.doctor_id, {
          id: p.doctor_id,
          full_name: p.full_name,
          specialty: p.specialty ?? null,
          institution_id: institutionId,
          review_state: "pending_review",
          default_line_id: p.default_line_id,
        });
      }
      return;
    }
    case "visit_scheduled": {
      if (!ev.visit_id) return;
      const p = ev.payload as unknown as VisitScheduledPayload;
      const existing = view.visits.get(ev.visit_id);
      if (existing) return; // la foto del servidor ya la incluye
      const doctor = view.doctors.get(p.doctor_id);
      view.visits.set(ev.visit_id, {
        id: ev.visit_id,
        doctor_id: p.doctor_id,
        institution_id: doctor?.institution_id ?? null,
        primary_line_id: p.line_ids[0]!,
        line_ids: p.line_ids,
        scheduled_at: p.scheduled_at,
        status: "scheduled",
        planned_by: p.planned_by ?? "rep",
        not_done_reason: null,
        updated_at: ev.device_ts,
      });
      return;
    }
    case "visit_rescheduled": {
      const visit = ev.visit_id ? view.visits.get(ev.visit_id) : undefined;
      if (!visit || visit.status !== "scheduled") return;
      const p = ev.payload as unknown as VisitRescheduledPayload;
      view.visits.set(visit.id, {
        ...visit,
        scheduled_at: p.scheduled_at,
        updated_at: ev.device_ts,
      });
      return;
    }
    case "visit_not_done": {
      const visit = ev.visit_id ? view.visits.get(ev.visit_id) : undefined;
      if (
        !visit ||
        (visit.status !== "scheduled" && visit.status !== "not_done")
      )
        return;
      const p = ev.payload as unknown as VisitNotDonePayload;
      view.visits.set(visit.id, {
        ...visit,
        status: "not_done",
        not_done_reason: p.reason,
        updated_at: ev.device_ts,
      });
      return;
    }
    case "visit_arrived": {
      const visit = ev.visit_id ? view.visits.get(ev.visit_id) : undefined;
      // Solo desde «agendada»: si la foto del servidor ya la tiene en visita, esa es la verdad (idempotente).
      if (!visit || visit.status !== "scheduled") return;
      const p = ev.payload as unknown as VisitTouchPayload;
      view.visits.set(visit.id, {
        ...visit,
        status: "in_progress",
        arrived_at: ev.device_ts,
        arrival_geo: geoOf(
          p.location,
          view.institutions.get(visit.institution_id ?? ""),
        ),
        updated_at: ev.device_ts,
      });
      return;
    }
    case "visit_finished": {
      const visit = ev.visit_id ? view.visits.get(ev.visit_id) : undefined;
      // «Terminé» también vale sobre una agendada (se olvidó el Llegué): queda sin hora de llegada.
      if (
        !visit ||
        (visit.status !== "in_progress" && visit.status !== "scheduled")
      )
        return;
      const p = ev.payload as unknown as VisitTouchPayload;
      view.visits.set(visit.id, {
        ...visit,
        status: "finished",
        finished_at: ev.device_ts,
        finish_geo: geoOf(
          p.location,
          view.institutions.get(visit.institution_id ?? ""),
        ),
        updated_at: ev.device_ts,
      });
      return;
    }
    case "visit_location_retried": {
      const visit = ev.visit_id ? view.visits.get(ev.visit_id) : undefined;
      if (!visit) return;
      const p = ev.payload as unknown as VisitLocationRetriedPayload;
      const key = p.moment === "arrival" ? "arrival_geo" : "finish_geo";
      const current = visit[key];
      // Solo reemplaza una ubicación que no servía; si ya está verificada (o «lejos») se queda como está.
      if (!current || !RETRYABLE_GEO.has(current.state)) return;
      view.visits.set(visit.id, {
        ...visit,
        [key]: geoOf(
          p.location,
          view.institutions.get(visit.institution_id ?? ""),
        ),
        updated_at: ev.device_ts,
      });
      return;
    }
    case "report_confirmed": {
      const report = ev.visit_id ? view.reports.get(ev.visit_id) : undefined;
      if (!report || report.status === "confirmed") return;
      const currentVisit = view.visits.get(report.visit_id);
      if (
        currentVisit?.report_due_at &&
        Date.parse(ev.device_ts) >= Date.parse(currentVisit.report_due_at)
      )
        return;
      view.reports.set(report.visit_id, {
        ...report,
        status: "confirmed",
        confirmed_at: ev.device_ts,
      });
      const visit = view.visits.get(report.visit_id);
      if (visit && visit.status !== "confirmed") {
        view.visits.set(visit.id, {
          ...visit,
          report_invalid_at: null,
          status: "confirmed",
          updated_at: ev.device_ts,
        });
      }
      return;
    }
    case "report_field_edited": {
      if (!ev.visit_id) return;
      const visit = view.visits.get(ev.visit_id);
      if (!visit) return;
      const existing = view.reports.get(ev.visit_id);
      if (
        !existing &&
        ![
          "finished",
          "in_call",
          "processing",
          "ready",
          "no_interview",
          "error",
        ].includes(visit.status)
      )
        return;
      const report = existing ?? {
        visit_id: visit.id,
        status: "ready" as const,
        complete: false,
        fields: {},
        confirmed_at: null,
        updated_at: ev.device_ts,
      };
      const p = ev.payload as unknown as ReportFieldEditedPayload;
      const value =
        typeof p.value === "string" ? p.value.trim() || null : p.value;
      const fields = {
        ...report.fields,
        [p.field]: { value, confidence: "high", source: "rep_edit" },
      };
      if (p.field === "next_action_date") {
        fields.next_action_due = {
          value,
          confidence: "high",
          source: "rep_edit",
        };
        fields.next_action_in_days = {
          value: null,
          confidence: "high",
          source: "rep_edit",
        };
      }
      view.reports.set(report.visit_id, {
        ...report,
        fields,
        complete: reportIsComplete(fields),
        updated_at: ev.device_ts,
      });
      if (report.status !== "confirmed") {
        view.visits.set(visit.id, {
          ...visit,
          report_mode: "written",
          status: ["finished", "in_call", "processing"].includes(visit.status)
            ? "ready"
            : visit.status,
          updated_at: ev.device_ts,
        });
      }
      return;
    }
    default:
      return; // tipo desconocido para esta versión de la app: no se muestra
  }
}
import { reportIsComplete } from "../lib/report";
