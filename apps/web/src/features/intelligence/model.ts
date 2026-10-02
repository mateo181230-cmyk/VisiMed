import { DOCTORS, INITIAL_VISITS, RECOMMENDATIONS, DEMO_TODAY } from './demoData'
import type { CalendarVisit, DemoState, DoctorProfile } from './types'

export const DEMO_STORAGE_KEY = 'uno-intelligence-demo-v1'
export const initialDemoState = (): DemoState => ({
  visits: [...INITIAL_VISITS],
  decisions: {},
  reviewed: [],
})

export function minutes(time: string): number {
  const [hour, minute] = time.split(':').map(Number)
  return hour! * 60 + minute!
}

export function endTime(time: string, duration: number): string {
  const value = minutes(time) + duration
  return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`
}

export function schedulingError(
  visit: CalendarVisit,
  visits: CalendarVisit[],
  doctors: DoctorProfile[] = DOCTORS,
  today = DEMO_TODAY,
): string | null {
  const doctor = doctors.find((d) => d.id === visit.doctorId)
  if (!doctor) return 'Selecciona un médico del panel de ejemplo.'
  if (!['GASTRU', 'RESPI', 'OSTRU'].includes(visit.line)) return 'Selecciona una línea.'
  const day = new Date(`${visit.day}T12:00:00Z`)
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(visit.day) ||
    !Number.isFinite(day.getTime()) ||
    day.toISOString().slice(0, 10) !== visit.day
  )
    return 'Revisa la fecha de la visita.'
  if (visit.day < today) return `Elige una fecha desde ${today}.`
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(visit.time)) return 'Elige una hora válida.'
  if (![15, 30, 45, 60].includes(visit.duration)) return 'Elige una duración válida.'
  const start = minutes(visit.time)
  if (start < 8 * 60 || start + visit.duration > 18 * 60)
    return 'La visita debe estar entre las 8:00 a. m. y las 6:00 p. m.'
  const conflict = visits.some((other) => {
    if (other.id === visit.id || other.day !== visit.day) return false
    const sameRep = doctors.find((d) => d.id === other.doctorId)?.representativeId === doctor.representativeId
    return sameRep && start < minutes(other.time) + other.duration && start + visit.duration > minutes(other.time)
  })
  return conflict ? 'Este visitador ya tiene una visita en esa franja. Elige otra hora.' : null
}

/** El estado de la demostración queda aislado de Dexie y de /v1/sync. */
export function readDemoState(): DemoState {
  try {
    const value = JSON.parse(sessionStorage.getItem(DEMO_STORAGE_KEY) ?? 'null') as DemoState | null
    if (
      !value ||
      !Array.isArray(value.visits) ||
      !Array.isArray(value.reviewed) ||
      !value.decisions ||
      typeof value.decisions !== 'object' ||
      Array.isArray(value.decisions)
    )
      return initialDemoState()
    if (
      value.visits.some(
        (v) =>
          !v ||
          typeof v.id !== 'string' ||
          !['existing', 'suggestion', 'manual'].includes(v.source) ||
          !DOCTORS.some((d) => d.id === v.doctorId) ||
          schedulingError(v, value.visits),
      )
    )
      return initialDemoState()
    if (new Set(value.visits.map((v) => v.id)).size !== value.visits.length) return initialDemoState()
    if (
      Object.entries(value.decisions).some(
        ([id, d]) =>
          (!id.startsWith('followup-pilot-demo-') && !RECOMMENDATIONS.some((r) => r.id === id)) ||
          !d ||
          !['accepted', 'dismissed'].includes(d.status),
      )
    )
      return initialDemoState()
    const validObservations = new Set(DOCTORS.flatMap((d) => d.observations.map((o) => o.id)))
    return {
      visits: value.visits,
      decisions: value.decisions,
      reviewed: value.reviewed.filter((id) => validObservations.has(id)),
    }
  } catch {
    return initialDemoState()
  }
}

export function shortDate(key: string): string {
  return new Intl.DateTimeFormat('es-CO', {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).format(new Date(`${key}T12:00:00Z`))
}

export function dayName(key: string): string {
  return new Intl.DateTimeFormat('es-CO', { weekday: 'short', timeZone: 'UTC' })
    .format(new Date(`${key}T12:00:00Z`))
    .replace('.', '')
}

export function daysBetween(earlier: string, later = DEMO_TODAY): number {
  return Math.round((Date.parse(`${later}T12:00:00Z`) - Date.parse(`${earlier}T12:00:00Z`)) / 86_400_000)
}
