import clsx from 'clsx'
import { ChevronLeft, ChevronRight, Plus, Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
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
  isDateKey,
  weekMonthLabel,
  todayKey,
  weekStart,
} from '../../lib/time'
import { useNow } from '../../lib/useNow'
import { ScheduleSheet } from './ScheduleSheet'
import { UnsentMark } from './VisitItems'
import { VisitSheet } from './VisitSheet'
import { NOT_DONE_LABEL, type VisitVM, useAgenda } from './useAgenda'

/** Agenda: semana completa y línea de tiempo del día elegido. */
export function WeekScreen() {
  const agenda = useAgenda()
  const now = useNow(60_000)
  const today = todayKey(agenda.tz, now)
  const [params, setParams] = useSearchParams()
  const requestedDay = params.get('fecha')
  const selectedDay = isDateKey(requestedDay) ? requestedDay : null
  const setSelectedDay = (next: string) => setParams((current) => {
    const updated = new URLSearchParams(current)
    updated.set('fecha', next)
    return updated
  })
  const [scheduling, setScheduling] = useState(false)
  const [opened, setOpened] = useState<VisitVM | null>(null)

  const openedVm = opened ? agenda.vm(agenda.visits.find((v) => v.id === opened.visit.id) ?? opened.visit) : null

  const day = selectedDay ?? today
  const monday = weekStart(day)
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(monday, i)), [monday])
  const visits = (agenda.byDay.get(day) ?? []).map((v) => agenda.vm(v))

  return (
    <>
      <ScreenHeader
        title="Agenda"
        subtitle={weekMonthLabel(monday)}
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
        <nav aria-label="Semana" className="grid grid-cols-[44px_minmax(0,1fr)_44px] items-center gap-1">
          <button
            type="button"
            aria-label="Semana anterior"
            onClick={() => setSelectedDay(addDays(day, -7))}
            className="grid size-11 shrink-0 place-items-center rounded-full text-muted active:bg-line/60"
          >
            <ChevronLeft size={22} />
          </button>
          <span className="text-center text-sm text-muted">Del {dayNumber(monday)} al {dayNumber(days[6]!)}</span>
          <button
            type="button"
            aria-label="Semana siguiente"
            onClick={() => setSelectedDay(addDays(day, 7))}
            className="grid size-11 shrink-0 place-items-center rounded-full text-muted active:bg-line/60"
          >
            <ChevronRight size={22} />
          </button>
          <ul className="col-span-3 row-start-2 grid min-w-0 grid-cols-7 gap-1.5">
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
            <span aria-hidden className="absolute top-3 bottom-3 left-[98px] w-px bg-brand/25 min-[375px]:left-[110px]" />
            {visits.map((vm) => {
              const cancelled = vm.visit.status === 'not_done'
              return (
                <li key={vm.visit.id} className="relative flex items-stretch gap-2 py-1.5 min-[375px]:gap-3">
                  <span className="w-[84px] shrink-0 pt-4 text-[13px] font-semibold whitespace-nowrap tabular-nums min-[375px]:w-[92px] min-[375px]:text-sm">
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
                    className="flex min-h-16 min-w-0 flex-1 items-center justify-between gap-2 rounded-card bg-white px-3 py-3 text-left shadow-[0_1px_2px_rgba(16,24,40,0.06)] active:bg-brand-50 min-[375px]:px-4"
                  >
                    <span className="min-w-0 flex-1">
                      <span className={clsx('block truncate font-semibold max-[374px]:line-clamp-2 max-[374px]:whitespace-normal', cancelled && 'text-muted line-through')}>
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
          Programar visita
        </Button>
      </div>

      <ScheduleSheet open={scheduling} onClose={() => setScheduling(false)} initialDay={day} agenda={agenda} />
      <VisitSheet vm={openedVm} tz={agenda.tz} onClose={() => setOpened(null)} />
    </>
  )
}
