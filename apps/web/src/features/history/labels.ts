/**
 * Cómo se muestra la ficha de una visita: etiquetas en español, qué filas van y cómo se corrige cada una.
 * Los valores llegan del servidor en inglés (`no_need_to_switch`); aquí se traducen.
 */
import type { ReportField, ReportRow, ReportValue } from '../../db/db'
import { formatLongDate } from '../../lib/time'
import type { EditableReportField } from '../../sync/events'

export const OUTCOME_LABEL: Record<string, string> = {
  order_taken: 'Hizo un pedido',
  commitment: 'Se comprometió',
  sample_requested: 'Pidió muestras',
  info_requested: 'Pidió información',
  follow_up_set: 'Quedó un seguimiento',
  neutral: 'Escuchó, sin compromiso',
  rejected: 'Rechazó',
  not_attended: 'No lo atendieron',
}

export const REASON_LABEL: Record<string, string> = {
  competitor_better: 'La competencia está mejor',
  no_need_to_switch: 'No necesita cambiar lo que usa',
  price: 'Precio',
  availability: 'Disponibilidad',
  needs_more_information: 'Necesita más información',
  no_time: 'Sin tiempo',
  other: 'Otro motivo',
  not_applicable: 'Hubo pedido',
}

export const CALL_FAILURE_LABEL: Record<string, string> = {
  'no-answer': 'No contestaste',
  no_answer: 'No contestaste',
  busy: 'Estabas ocupado',
  voicemail: 'Entró el buzón',
  incomplete: 'Pediste que te llamaran más tarde',
  timeout: 'No se pudo completar la llamada',
  provider_error: 'No se pudo marcar',
  dial_lost: 'No se pudo marcar',
}

export type EditorSpec =
  | { kind: 'scale' }
  | { kind: 'bool' }
  | { kind: 'choice'; options: ReadonlyArray<readonly [string, string]> }
  | { kind: 'text'; max: number; multiline?: boolean }

export interface FieldDef {
  key: EditableReportField
  label: string
  editor: EditorSpec
  /** Fila solo si esta condición se cumple (por ejemplo, el motivo solo si no hubo pedido). */
  when?: (report: ReportRow) => boolean
}

const choices = (labels: Record<string, string>, skip: string[] = []): ReadonlyArray<readonly [string, string]> =>
  Object.entries(labels).filter(([k]) => !skip.includes(k))

/** Las filas de la ficha, en el orden en que se leen. */
export const FIELD_DEFS: readonly FieldDef[] = [
  { key: 'interest_level', label: 'Interés', editor: { kind: 'scale' } },
  { key: 'visit_outcome', label: 'Resultado', editor: { kind: 'choice', options: choices(OUTCOME_LABEL) } },
  { key: 'order_taken', label: '¿Hubo pedido?', editor: { kind: 'bool' } },
  {
    key: 'no_order_reason',
    label: 'Si no, ¿por qué?',
    editor: { kind: 'choice', options: choices(REASON_LABEL, ['not_applicable']) },
    when: (r) => r.fields.order_taken?.value !== true,
  },
  { key: 'objection', label: 'Objeción', editor: { kind: 'text', max: 140 } },
  { key: 'competitor', label: 'Competencia', editor: { kind: 'text', max: 80 } },
  { key: 'commitment', label: 'Compromiso', editor: { kind: 'text', max: 140 } },
  { key: 'next_action', label: 'Próximo paso', editor: { kind: 'text', max: 140 } },
  { key: 'territory_signal', label: 'Territorio', editor: { kind: 'text', max: 200, multiline: true } },
]

export const SUMMARY_DEF: FieldDef = {
  key: 'summary',
  label: 'Resumen',
  editor: { kind: 'text', max: 280, multiline: true },
}

export function fieldValue(report: ReportRow, key: string): ReportValue {
  return report.fields[key]?.value ?? null
}

/** Texto de una fila, o `null` si no hay dato. */
export function displayValue(key: string, value: ReportValue): string | null {
  if (value === null || value === '') return null
  switch (key) {
    case 'interest_level':
      return `${value} de 5`
    case 'visit_outcome':
      return OUTCOME_LABEL[String(value)] ?? String(value)
    case 'order_taken':
      return value === true ? 'Sí' : 'No'
    case 'no_order_reason':
      return REASON_LABEL[String(value)] ?? String(value)
    default:
      return String(value)
  }
}

/** «Martes, 13 de octubre» de `next_action_due` (`YYYY-MM-DD`), o `null`. */
export function dueDateLabel(report: ReportRow): string | null {
  const due = fieldValue(report, 'next_action_due')
  return typeof due === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(due) ? formatLongDate(due) : null
}

export function isDoubtful(field: ReportField | undefined): boolean {
  return !!field && field.confidence === 'low' && field.source !== 'rep_edit'
}

/** Frase corta para la lista del historial: el resumen, o lo esencial armado con los datos. */
export function reportSnippet(report: ReportRow): string {
  const summary = fieldValue(report, 'summary')
  if (typeof summary === 'string' && summary) return summary
  const parts = [
    displayValue('interest_level', fieldValue(report, 'interest_level')),
    displayValue('visit_outcome', fieldValue(report, 'visit_outcome')),
  ].filter((x): x is string => !!x)
  return parts.length ? parts.join(' · ') : 'Resumen listo'
}
