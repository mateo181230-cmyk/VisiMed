import { useLiveQuery } from 'dexie-react-hooks'
import { useMemo } from 'react'
import {
  type DoctorRow,
  type InstitutionRow,
  type LineRow,
  type ReportRow,
  type VisitRow,
  db,
  getMeta,
} from '../../db/db'
import { DEFAULT_TZ, dateKey } from '../../lib/time'
import type { TouchMoment } from '../../sync/events'
import { overlay } from '../../sync/overlay'

export interface VisitVM {
  visit: VisitRow
  doctor: DoctorRow | undefined
  institution: InstitutionRow | undefined
  lines: LineRow[]
  /** Hay cambios de esta visita que todavía no se confirmaron en el servidor. */
  unsent: boolean
  /** Qué toque de esta visita está esperando su ubicación ahora mismo (`null` si ninguno). */
  capturing: TouchMoment | null
}

export interface Agenda {
  loading: boolean
  tz: string
  lines: LineRow[]
  doctors: DoctorRow[]
  institutions: InstitutionRow[]
  /** Visitas ya con los eventos pendientes aplicados encima, ordenadas por hora. */
  visits: VisitRow[]
  byDay: Map<string, VisitRow[]>
  /** Fichas (resúmenes) por visita, con las correcciones aún sin enviar ya aplicadas. */
  reports: Map<string, ReportRow>
  vm: (visit: VisitRow) => VisitVM
}

const EMPTY: never[] = []

/** Lee de la base local (nunca de la red) y aplica encima lo que aún no se confirmó. */
export function useAgenda(): Agenda {
  const raw = useLiveQuery(async () => {
    const [visits, doctors, institutions, lines, reports, outbox, tz] = await Promise.all([
      db.visits.toArray(),
      db.doctors.toArray(),
      db.institutions.toArray(),
      db.lines.toArray(),
      db.reports.toArray(),
      db.outbox.toArray(),
      getMeta<string>('timezone'),
    ])
    const view = overlay({ visits, doctors, institutions, reports }, outbox)
    const unsentVisits = new Set(
      outbox
        .filter((e) => (e.status === 'capturing' || e.status === 'pending' || e.status === 'sending') && e.visit_id)
        .map((e) => e.visit_id as string),
    )
    const capturingVisits = new Map<string, TouchMoment>(
      outbox
        .filter((e) => e.status === 'capturing' && e.visit_id)
        .map((e) => [e.visit_id as string, e.type === 'visit_finished' ? 'finish' : 'arrival'] as const),
    )
    return {
      tz: tz ?? DEFAULT_TZ,
      lines,
      visits: [...view.visits.values()],
      doctors: [...view.doctors.values()],
      institutions: [...view.institutions.values()],
      reports: view.reports,
      unsentVisits,
      capturingVisits,
    }
  }, [])

  return useMemo<Agenda>(() => {
    const tz = raw?.tz ?? DEFAULT_TZ
    const doctors = raw?.doctors ?? EMPTY
    const institutions = raw?.institutions ?? EMPTY
    const lines = raw?.lines ?? EMPTY
    const visits = [...(raw?.visits ?? EMPTY)].sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at))
    const doctorById = new Map(doctors.map((d) => [d.id, d]))
    const institutionById = new Map(institutions.map((i) => [i.id, i]))
    const lineById = new Map(lines.map((l) => [l.id, l]))
    const byDay = new Map<string, VisitRow[]>()
    for (const v of visits) {
      const key = dateKey(v.scheduled_at, tz)
      const list = byDay.get(key)
      if (list) list.push(v)
      else byDay.set(key, [v])
    }
    return {
      loading: raw === undefined,
      tz,
      lines,
      doctors,
      institutions,
      visits,
      byDay,
      reports: raw?.reports ?? new Map<string, ReportRow>(),
      vm: (visit) => ({
        visit,
        doctor: doctorById.get(visit.doctor_id),
        institution: institutionById.get(visit.institution_id ?? '') ?? undefined,
        lines: visit.line_ids.map((id) => lineById.get(id)).filter((l): l is LineRow => !!l),
        unsent: raw?.unsentVisits.has(visit.id) ?? false,
        capturing: raw?.capturingVisits.get(visit.id) ?? null,
      }),
    }
  }, [raw])
}

/** Estados en los que la visita ya se realizó (sirven para el avance del día). */
export const DONE_STATUSES: ReadonlySet<string> = new Set([
  'finished',
  'in_call',
  'processing',
  'ready',
  'confirmed',
  'no_interview',
  'error',
])

export const STATUS_LABEL: Record<string, string> = {
  scheduled: 'Agendada',
  in_progress: 'En visita',
  finished: 'Terminada',
  not_done: 'No se realizó',
  in_call: 'Llamada en curso',
  processing: 'Procesando',
  ready: 'Lista para confirmar',
  error: 'Error',
  confirmed: 'Confirmada',
  no_interview: 'Sin entrevista',
}

export const NOT_DONE_LABEL: Record<string, string> = {
  doctor_unavailable: 'El médico no atendió',
  cancelled_by_office: 'Cancelada por el consultorio',
  rescheduled: 'Se reprogramó',
  other: 'Otro motivo',
}
