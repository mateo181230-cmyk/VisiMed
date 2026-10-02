import { Bell, ClipboardCheck, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ScreenHeader } from '../../components/ScreenHeader'
import { ProfileLink } from '../../components/ProfileLink'
import { SyncPill } from '../../components/SyncPill'
import { Button, Card, SectionTitle, Skeleton } from '../../components/ui'
import { formatLongDate, todayKey } from '../../lib/time'
import { useNow } from '../../lib/useNow'
import { useToConfirmCount } from '../history/useHistory'
import { VisitActions } from '../visit/VisitActions'
import { ScheduleSheet } from './ScheduleSheet'
import { NextVisitCard, VisitRowItem } from './VisitItems'
import { VisitSheet } from './VisitSheet'
import { DONE_STATUSES, type VisitVM, useAgenda } from './useAgenda'

const LATE_AFTER_MS = 60 * 60 * 1000 // una visita agendada sin cerrar 1 h después se pasa a «Por resolver»
const NOW_WINDOW_MS = 30 * 60 * 1000

/** Hoy (doc 01 §8.3, S3): la visita actual siempre al frente, y lo que sigue. */
export function TodayScreen() {
  const agenda = useAgenda()
  const now = useNow()
  const toConfirm = useToConfirmCount()
  const [scheduling, setScheduling] = useState(false)
  const [selected, setSelected] = useState<VisitVM | null>(null)

  const day = todayKey(agenda.tz, now)
  const groups = useMemo(() => {
    const visits = (agenda.byDay.get(day) ?? []).map((v) => agenda.vm(v))
    const t = now.getTime()
    const done = visits.filter((v) => DONE_STATUSES.has(v.visit.status))
    const cancelled = visits.filter((v) => v.visit.status === 'not_done')
    const open = visits.filter((v) => v.visit.status === 'scheduled' || v.visit.status === 'in_progress')
    const late = open.filter(
      (v) => v.visit.status === 'scheduled' && Date.parse(v.visit.scheduled_at) < t - LATE_AFTER_MS,
    )
    // La visita en curso va siempre al frente: es a la que le toca «Terminé».
    const upcoming = [
      ...open.filter((v) => v.visit.status === 'in_progress'),
      ...open.filter((v) => v.visit.status === 'scheduled' && !late.includes(v)),
    ]
    const [next, ...after] = upcoming
    const planned = visits.length - cancelled.length
    return { visits, done, cancelled, late, next, after, planned }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agenda, day, now])

  const { next } = groups
  // La hoja abierta siempre muestra el estado actual de la visita (por ejemplo, tras tocar «Llegué»).
  const openedVm = selected ? agenda.vm(agenda.visits.find((v) => v.id === selected.visit.id) ?? selected.visit) : null
  const isNow = next && Math.abs(Date.parse(next.visit.scheduled_at) - now.getTime()) <= NOW_WINDOW_MS
  const progress = groups.planned > 0 ? Math.round((groups.done.length / groups.planned) * 100) : 0

  return (
    <>
      <ScreenHeader
        title="Hoy"
        subtitle={formatLongDate(day)}
        right={
          <>
            <SyncPill />
            <Link
              to="/mas/avisos"
              aria-label="Avisos"
              className="grid size-11 place-items-center rounded-full text-ink active:bg-line/60"
            >
              <Bell size={24} />
            </Link>
            <ProfileLink />
          </>
        }
      />

      <div className="space-y-6 px-5 pb-6">
        {agenda.loading ? (
          <div className="space-y-4">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-64" />
          </div>
        ) : groups.visits.length === 0 ? (
          <Card className="p-6 text-center">
            <p className="text-lg font-bold">Sin visitas hoy</p>
            <p className="mt-1 text-muted">Agenda tu primera visita del día.</p>
            <Button className="mt-5" size="lg" block icon={<Plus size={22} />} onClick={() => setScheduling(true)}>
              Agendar visita
            </Button>
          </Card>
        ) : (
          <>
            <div>
              <div
                className="h-2 overflow-hidden rounded-full bg-line"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={progress}
                aria-label="Avance del día"
              >
                <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${progress}%` }} />
              </div>
              <p className="mt-2 text-[15px] font-medium">
                {groups.done.length} de {groups.planned}{' '}
                {groups.planned === 1 ? 'visita realizada' : 'visitas realizadas'}
              </p>
            </div>

            {toConfirm > 0 && (
              <Link
                to="/historial"
                className="flex min-h-14 items-center gap-3 rounded-card bg-brand-50 px-4 py-3 text-navy active:bg-brand-100"
              >
                <ClipboardCheck size={24} className="shrink-0 text-brand" aria-hidden />
                <span className="flex-1 font-semibold">
                  {toConfirm === 1 ? '1 resumen pendiente' : `${toConfirm} resúmenes pendientes`}
                </span>
                <span className="font-bold text-brand">Ver</span>
              </Link>
            )}

            {next ? (
              <NextVisitCard
                vm={next}
                tz={agenda.tz}
                label={next.visit.status === 'in_progress' || isNow ? 'Ahora' : 'Siguiente'}
                onOpen={() => setSelected(next)}
              >
                <VisitActions vm={next} tz={agenda.tz} />
              </NextVisitCard>
            ) : (
              <Card className="p-5 text-center">
                <p className="text-lg font-bold">No tienes más visitas pendientes hoy</p>
              </Card>
            )}

            {groups.late.length > 0 && (
              <section className="space-y-2">
                <SectionTitle>Por resolver</SectionTitle>
                <Card className="divide-y divide-line overflow-hidden">
                  {groups.late.map((v) => (
                    <VisitRowItem key={v.visit.id} vm={v} tz={agenda.tz} tone="warn" onOpen={() => setSelected(v)} />
                  ))}
                </Card>
              </section>
            )}

            {groups.after.length > 0 && (
              <section className="space-y-2">
                <SectionTitle>Después</SectionTitle>
                <Card className="divide-y divide-line overflow-hidden">
                  {groups.after.map((v) => (
                    <VisitRowItem key={v.visit.id} vm={v} tz={agenda.tz} onOpen={() => setSelected(v)} />
                  ))}
                </Card>
              </section>
            )}

            {groups.done.length + groups.cancelled.length > 0 && (
              <section className="space-y-2">
                <SectionTitle>Realizadas</SectionTitle>
                <Card className="divide-y divide-line overflow-hidden">
                  {[...groups.done, ...groups.cancelled].map((v) => (
                    <VisitRowItem key={v.visit.id} vm={v} tz={agenda.tz} tone="muted" onOpen={() => setSelected(v)} />
                  ))}
                </Card>
              </section>
            )}

            <Button variant="soft" block size="lg" icon={<Plus size={22} />} onClick={() => setScheduling(true)}>
              Agregar visita
            </Button>
          </>
        )}
      </div>

      <ScheduleSheet open={scheduling} onClose={() => setScheduling(false)} initialDay={day} agenda={agenda} />
      <VisitSheet vm={openedVm} tz={agenda.tz} onClose={() => setSelected(null)} />
    </>
  )
}
