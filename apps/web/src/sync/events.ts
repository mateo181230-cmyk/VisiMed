/**
 * Eventos que el teléfono envía por ``POST /v1/sync`` (doc 03 §5.2; contrato en
 * ``docs/contratos/sync-events.md``). Los constructores devuelven el par ``(tipo, payload)`` ya
 * con la forma exacta que valida el servidor.
 */

export interface InstitutionPayload {
  id: string
  name: string
  address?: string | null
  city?: string | null
}

export interface DoctorCreatedPayload {
  doctor_id: string
  full_name: string
  specialty?: string | null
  default_line_id: string
  institution_id?: string | null
  institution?: InstitutionPayload | null
}

export interface VisitScheduledPayload {
  doctor_id: string
  line_ids: string[]
  /** ISO 8601 UTC */
  scheduled_at: string
  planned_by?: 'rep' | 'spontaneous'
}

export interface VisitRescheduledPayload {
  scheduled_at: string
}

export const NOT_DONE_REASONS = ['doctor_unavailable', 'cancelled_by_office', 'rescheduled', 'other'] as const
export type NotDoneReason = (typeof NOT_DONE_REASONS)[number]

export interface VisitNotDonePayload {
  reason: NotDoneReason
}

/** Ubicación de un toque tal como viaja al servidor (`docs/contratos/sync-events.md`). */
export interface WireLocation {
  lat: number
  lng: number
  precision_m: number
  /** ISO 8601 UTC: cuándo tomó el sistema la lectura */
  fix_ts: string
  source: 'gps' | 'reused'
}

/** Payload de `visit_arrived` y `visit_finished`. `location = null` si no hubo lectura: el toque vale igual. */
export interface VisitTouchPayload {
  location: WireLocation | null
  permission?: 'granted' | 'denied' | 'prompt'
  duration_ms?: number | null
  error?: string | null
}

export type TouchMoment = 'arrival' | 'finish'

export interface VisitLocationRetriedPayload {
  moment: TouchMoment
  location: WireLocation
  permission?: 'granted' | 'denied' | 'prompt'
  duration_ms?: number | null
}

/** Campos de la ficha que el visitador puede corregir (el servidor valida cada valor). */
export const EDITABLE_REPORT_FIELDS = [
  'interest_level',
  'visit_outcome',
  'order_taken',
  'no_order_reason',
  'objection',
  'competitor',
  'commitment',
  'next_action',
  'territory_signal',
  'summary',
] as const
export type EditableReportField = (typeof EDITABLE_REPORT_FIELDS)[number]

export interface ReportFieldEditedPayload {
  field: EditableReportField
  /** `null` (o texto vacío) borra el campo. */
  value: string | number | boolean | null
}

export type EventSpec =
  | { type: 'doctor_created'; visitId: null; payload: DoctorCreatedPayload }
  | { type: 'visit_scheduled'; visitId: string; payload: VisitScheduledPayload }
  | { type: 'visit_rescheduled'; visitId: string; payload: VisitRescheduledPayload }
  | { type: 'visit_not_done'; visitId: string; payload: VisitNotDonePayload }
  | { type: 'visit_arrived'; visitId: string; payload: VisitTouchPayload }
  | { type: 'visit_finished'; visitId: string; payload: VisitTouchPayload }
  | { type: 'visit_location_retried'; visitId: string; payload: VisitLocationRetriedPayload }
  | { type: 'report_confirmed'; visitId: string; payload: Record<string, never> }
  | { type: 'report_field_edited'; visitId: string; payload: ReportFieldEditedPayload }

export const doctorCreated = (payload: DoctorCreatedPayload): EventSpec => ({
  type: 'doctor_created',
  visitId: null,
  payload,
})

export const visitScheduled = (visitId: string, payload: VisitScheduledPayload): EventSpec => ({
  type: 'visit_scheduled',
  visitId,
  payload,
})

export const visitRescheduled = (visitId: string, scheduledAt: string): EventSpec => ({
  type: 'visit_rescheduled',
  visitId,
  payload: { scheduled_at: scheduledAt },
})

export const visitNotDone = (visitId: string, reason: NotDoneReason): EventSpec => ({
  type: 'visit_not_done',
  visitId,
  payload: { reason },
})

export const visitArrived = (visitId: string, payload: VisitTouchPayload): EventSpec => ({
  type: 'visit_arrived',
  visitId,
  payload,
})

export const visitFinished = (visitId: string, payload: VisitTouchPayload): EventSpec => ({
  type: 'visit_finished',
  visitId,
  payload,
})

export const visitLocationRetried = (visitId: string, payload: VisitLocationRetriedPayload): EventSpec => ({
  type: 'visit_location_retried',
  visitId,
  payload,
})

export const reportConfirmed = (visitId: string): EventSpec => ({
  type: 'report_confirmed',
  visitId,
  payload: {},
})

export const reportFieldEdited = (
  visitId: string,
  field: EditableReportField,
  value: ReportFieldEditedPayload['value'],
): EventSpec => ({
  type: 'report_field_edited',
  visitId,
  payload: { field, value },
})
