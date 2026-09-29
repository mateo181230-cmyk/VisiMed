import { useLiveQuery } from 'dexie-react-hooks'
import { useMemo } from 'react'
import { type ReportRow, db } from '../../db/db'
import { addDays, dateKey, formatLongDate, todayKey } from '../../lib/time'
import { useNow } from '../../lib/useNow'
import { LIVE_STATUSES } from '../../sync/overlay'
import { type Agenda, type VisitVM, useAgenda } from '../agenda/useAgenda'

/** Visitas que ya ocurrieron (o se cayeron): las que tienen algo que contar en el historial. */
export const HISTORY_STATUSES: ReadonlySet<string> = new Set([
  'finished',
  'in_call',
  'processing',
  'ready',
  'confirmed',
  'no_interview',
  'error',
  'not_done',
])

export interface HistoryItem {
  vm: VisitVM
  report: ReportRow | null
  /** Instante que ordena la visita dentro del historial (cuando terminó, o si no, cuando estaba agendada). */
  at: string
}

export interface HistoryGroup {
  day: string
  title: string
  items: HistoryItem[]
}

export function dayTitle(day: string, today: string): string {
  if (day === today) return 'Hoy'
  if (day === addDays(today, -1)) return 'Ayer'
  return formatLongDate(day)
}

/** Agrupa por día local, del más reciente al más antiguo, y dentro de cada día lo último primero. */
export function groupHistory(agenda: Agenda, now: Date): HistoryGroup[] {
  const today = todayKey(agenda.tz, now)
  const byDay = new Map<string, HistoryItem[]>()
  for (const visit of agenda.visits) {
    if (!HISTORY_STATUSES.has(visit.status)) continue
    const at = visit.finished_at ?? visit.arrived_at ?? visit.scheduled_at
    const day = dateKey(at, agenda.tz)
    const item: HistoryItem = { vm: agenda.vm(visit), report: agenda.reports.get(visit.id) ?? null, at }
    const list = byDay.get(day)
    if (list) list.push(item)
    else byDay.set(day, [item])
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([day, items]) => ({
      day,
      title: dayTitle(day, today),
      items: items.sort((a, b) => b.at.localeCompare(a.at)),
    }))
}

export function countToConfirm(groups: HistoryGroup[]): number {
  return groups.reduce((n, g) => n + g.items.filter((i) => i.report?.status === 'ready').length, 0)
}

export function useHistory() {
  const agenda = useAgenda()
  const now = useNow(60_000)
  return useMemo(() => {
    const groups = groupHistory(agenda, now)
    return { loading: agenda.loading, tz: agenda.tz, groups, toConfirm: countToConfirm(groups) }
  }, [agenda, now])
}

/** Cuántos resúmenes esperan confirmación (para la insignia de la barra inferior). Ligero: no arma la agenda. */
export function useToConfirmCount(): number {
  return (
    useLiveQuery(async () => {
      const [ready, outbox] = await Promise.all([
        db.reports.where('status').equals('ready').toArray(),
        db.outbox.toArray(),
      ])
      const confirming = new Set(
        outbox
          .filter((e) => e.type === 'report_confirmed' && LIVE_STATUSES.has(e.status) && e.visit_id)
          .map((e) => e.visit_id as string),
      )
      return ready.filter((r) => !confirming.has(r.visit_id)).length
    }, []) ?? 0
  )
}
