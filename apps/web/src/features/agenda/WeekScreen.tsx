import clsx from 'clsx'
import { ChevronLeft, ChevronRight, Plus, Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ScreenHeader } from '../../components/ScreenHeader'
import { ProfileLink } from '../../components/ProfileLink'
import { SyncPill } from '../../components/SyncPill'
import { Button, Card, Skeleton } from '../../components/ui'
import {
  addDays,
  dayLetter,
  dayNumber,
  formatDayTitle,
  formatTime,
  monthName,
  todayKey,
  weekStart,
} from '../../lib/time'
import { useNow } from '../../lib/useNow'
import { ScheduleSheet } from './ScheduleSheet'
import { UnsentMark } from './VisitItems'
import { VisitSheet } from './VisitSheet'
import { NOT_DONE_LABEL, type VisitVM, useAgenda } from './useAgenda'

/** Agenda (doc 01 §8.3, S8): semana de lunes a sábado y línea de tiempo del día elegido. */
export function WeekScreen() {
  const agenda = useAgenda()
  const now = useNow(60_000)
  const today = todayKey(agenda.tz, now)
  const [selectedDay, setSelectedDay] = useState<string | null>(null)
  const [scheduling, setScheduling] = useState(false)
  const [opened, setOpened] = useState<VisitVM | null>(null)

  const openedVm = opened ? agenda.vm(agenda.visits.find((v) => v.id === opened.visit.id) ?? opened.visit) : null

  const day = selectedDay ?? today
  const monday = weekStart(day)
  const days = useMemo(() => Array.from({ length: 6 }, (_, i) => addDays(monday, i)), [monday])
  const visits = (agenda.byDay.get(day) ?? []).map((v) => agenda.vm(v))

  return (
    <>
      <ScreenHeader
        title="Agenda"
        subtitle={`${monthName(monday).replace(/^./, (c) => c.toUpperCase())} ${monday.slice(0, 4)}`}
        right={
          <>
            <SyncPill />
            <ProfileLink />
          </>
        }
      />

      <div className="space-y-5 px-5 pb-6">
        <Link
          to="/inteligencia"
          className="flex items-center gap-3 rounded-control border border-brand/15 bg-brand-50 px-4 py-3"
        >
          <Sparkles size={20} className="shrink-0 text-brand" />
          <span className="flex-1">
            <strong className="block text-sm text-navy">Tu próxima visita sugerida</strong>
            <span className="block text-xs text-muted">Ver recomendaciones</span>
          </span>
          <ChevronRight size={17} className="text-brand" />
        </Link>
        <nav aria-label="Semana" className="flex items-center gap-1">
          <button
            type="button"
            aria-label="Semana anterior"
            onClick={() => setSelectedDay(addDays(day, -7))}
            className="grid size-11 shrink-0 place-items-center rounded-full text-muted active:bg-line/60"
          >
            <ChevronLeft size={22} />
          </button>
          <ul className="grid flex-1 grid-cols-6 gap-1.5">
            {days.map((d) => {
              const count = (agenda.byDay.get(d) ?? []).filter((v) => v.status !== 'not_done').length
              const active = d === day
              return (
                <li key={d}>
                  <button
                    type="button"
                    onClick={() => setSelectedDay(d)}
                    aria-pressed={active}
                    aria-label={`${formatDayTitle(d)}, ${count} ${count === 1 ? 'visita' : 'visitas'}`}
                    className={clsx(
                      'flex min-h-[68px] w-full flex-col items-center justify-center rounded-control text-sm transition-colors',
                      active ? 'bg-brand text-white' : 'bg-white text-ink active:bg-brand-50',
                      d === today && !active && 'ring-2 ring-brand/40',
                    )}
                  >
                    <span className={clsx('text-xs font-semibold', active ? 'text-white/85' : 'text-muted')}>
                      {dayLetter(d)}
                    </span>
                    <span className="text-lg leading-tight font-bold">{dayNumber(d)}</span>
                    <span
                      aria-hidden
                      className={clsx(
                        'mt-0.5 h-1.5 min-w-1.5 rounded-full px-0.5',
                        count > 0 ? (active ? 'bg-white' : 'bg-brand') : 'bg-transparent',
                      )}
                    />
                  </button>
                </li>
              )
            })}
          </ul>
          <button
            type="button"
            aria-label="Semana siguiente"
            onClick={() => setSelectedDay(addDays(day, 7))}
            className="grid size-11 shrink-0 place-items-center rounded-full text-muted active:bg-line/60"
          >
            <ChevronRight size={22} />
          </button>
        </nav>

        <h2 className="px-1 text-xl font-bold">
          {formatDayTitle(day)}
          {day === today && <span className="ml-2 align-middle text-sm font-semibold text-brand">Hoy</span>}
        </h2>

        {agenda.loading ? (
          <Skeleton className="h-48" />
        ) : visits.length === 0 ? (
          <Card className="p-5 text-center text-muted">Sin visitas este día.</Card>
        ) : (
          <ol className="relative">
            <span aria-hidden className="absolute top-3 bottom-3 left-[92px] w-px bg-brand/25" />
            {visits.map((vm) => {
              const cancelled = vm.visit.status === 'not_done'
              return (
                <li key={vm.visit.id} className="relative flex items-stretch gap-3 py-1.5">
                  <span className="w-[76px] shrink-0 pt-4 text-[15px] font-semibold tabular-nums">
                    {formatTime(vm.visit.scheduled_at, agenda.tz)}
                  </span>
                  <span
                    aria-hidden
                    className={clsx(
                      'relative z-10 mt-[22px] size-3 shrink-0 rounded-full ring-4 ring-canvas',
                      cancelled ? 'bg-line' : 'bg-brand',
                    )}
                  />
                  <button
                    type="button"
                    onClick={() => setOpened(vm)}
                    className="flex min-h-16 flex-1 items-center justify-between gap-2 rounded-card bg-white px-4 py-3 text-left shadow-[0_1px_2px_rgba(16,24,40,0.06)] active:bg-brand-50"
                  >
                    <span className="min-w-0">
                      <span className={clsx('block truncate font-semibold', cancelled && 'text-muted line-through')}>
                        {vm.doctor?.full_name ?? 'Médico'}
                      </span>
                      <span className="block truncate text-sm text-muted">
                        {cancelled
                          ? `No se realizó · ${NOT_DONE_LABEL[vm.visit.not_done_reason ?? ''] ?? ''}`
                          : (vm.institution?.name ?? 'Sin institución')}
                      </span>
                    </span>
                    {vm.unsent ? (
                      <UnsentMark />
                    ) : (
                      <ChevronRight size={20} className="shrink-0 text-muted" aria-hidden />
                    )}
                  </button>
                </li>
              )
            })}
          </ol>
        )}

        <Button variant="soft" block size="lg" icon={<Plus size={22} />} onClick={() => setScheduling(true)}>
          Agregar visita
        </Button>
      </div>

      <ScheduleSheet open={scheduling} onClose={() => setScheduling(false)} initialDay={day} agenda={agenda} />
      <VisitSheet vm={openedVm} tz={agenda.tz} onClose={() => setOpened(null)} />
    </>
  )
}
