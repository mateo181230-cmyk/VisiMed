import type { ReportField } from '../db/db'

export const REQUIRED_REPORT_FIELDS = [
  'products_discussed',
  'visit_objective',
  'discussion',
  'commitment',
  'next_action',
  'receptiveness_score',
  'visit_outcome',
] as const

export function reportIsComplete(fields: Record<string, ReportField>): boolean {
  const has = (key: string) =>
    fields[key]?.value !== null &&
    fields[key]?.value !== undefined &&
    fields[key]?.value !== '' &&
    fields[key]?.value !== 'unknown' &&
    fields[key]?.confidence !== 'low'
  return fields.visit_outcome?.value === 'not_attended' ? has('summary') : REQUIRED_REPORT_FIELDS.every(has)
}
