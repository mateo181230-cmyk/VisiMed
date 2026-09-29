import { Building2, CalendarClock, Layers, MapPin, Stethoscope, User } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Sheet } from '../../components/Sheet'
import { useToast } from '../../components/Toast'
import { Button, Chip, Notice } from '../../components/ui'
import { dateKey, formatLongDate, formatTime, hhmm, localToUtc } from '../../lib/time'
import { NOT_DONE_REASONS, type NotDoneReason, visitNotDone, visitRescheduled } from '../../sync/events'
import { enqueue } from '../../sync/outbox'
import { TouchSummary, VisitActions } from '../visit/VisitActions'
import { TimePicker } from './TimePicker'
import { NOT_DONE_LABEL, STATUS_LABEL, type VisitVM } from './useAgenda'

interface Props {
  vm: VisitVM | null
  tz: string
  onClose: () => void
}

type Mode = 'view' | 'reschedule' | 'not_done'

/** Detalle de una visita y sus acciones de agenda: cambiar la hora o marcarla «No se realizó». */
export function VisitSheet({ vm, tz, onClose }: Props) {
  const toast = useToast()
  const [mode, setMode] = useState<Mode>('view')
  const [day, setDay] = useState('')
  const [time, setTime] = useState<string | null>(null)

  const visitId = vm?.visit.id
  useEffect(() => {
    setMode('view')
    if (vm) {
      setDay(dateKey(vm.visit.scheduled_at, tz))
      setTime(hhmm(vm.visit.scheduled_at, tz))
    }
    // Solo se reinicia al abrir otra visita.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visitId])

  if (!vm) return null
  const { visit, doctor, institution, lines } = vm
  const editable = visit.status === 'scheduled'

  async function reschedule(): Promise<void> {
    if (!time) return
    const when = localToUtc(day, time, tz)
    await enqueue(visitRescheduled(visit.id, when.toISOString()))
    toast.show(`Visita movida · ${formatTime(when, tz)}`)
    onClose()
  }

  async function notDone(reason: NotDoneReason): Promise<void> {
    await enqueue(visitNotDone(visit.id, reason))
    toast.show('Marcada como «No se realizó»')
    onClose()
  }

  const changed = time !== null && (day !== dateKey(visit.scheduled_at, tz) || time !== hhmm(visit.scheduled_at, tz))

  return (
    <Sheet
      open
      onClose={onClose}
      title={doctor?.full_name ?? 'Visita'}
      footer={
        mode === 'reschedule' ? (
          <Button size="lg" block disabled={!changed} onClick={() => void reschedule()}>
            Guardar hora
          </Button>
        ) : undefined
      }
    >
      <div className="space-y-5 pt-1">
        <div>
          <p className="text-[34px] leading-none font-extrabold tracking-tight">{formatTime(visit.scheduled_at, tz)}</p>
          <p className="mt-1 text-base text-muted">{formatLongDate(dateKey(visit.scheduled_at, tz))}</p>
        </div>

        <ul className="space-y-2.5 text-base">
          {doctor && (
            <li className="flex items-center gap-3">
              <User size={20} className="shrink-0 text-muted" />
              {doctor.full_name}
            </li>
          )}
          {doctor?.specialty && (
            <li className="flex items-center gap-3">
              <Stethoscope size={20} className="shrink-0 text-muted" />
              {doctor.specialty}
            </li>
          )}
          {institution && (
            <li className="flex items-center gap-3">
              <Building2 size={20} className="shrink-0 text-muted" />
              {institution.name}
            </li>
          )}
          {institution?.address && (
            <li className="flex items-center gap-3">
              <MapPin size={20} className="shrink-0 text-muted" />
              {institution.address}
            </li>
          )}
          {lines.length > 0 && (
            <li className="flex items-center gap-3">
              <Layers size={20} className="shrink-0 text-muted" />
              {lines.map((l) => l.name).join(' · ')}
            </li>
          )}
        </ul>

        {vm.unsent && <Notice tone="info">Guardada en tu teléfono. Se enviará cuando haya conexión.</Notice>}

        {!editable && visit.status !== 'in_progress' && (
          <Notice tone={visit.status === 'not_done' ? 'warn' : 'info'}>
            {STATUS_LABEL[visit.status] ?? visit.status}
            {visit.not_done_reason ? ` · ${NOT_DONE_LABEL[visit.not_done_reason] ?? visit.not_done_reason}` : ''}
          </Notice>
        )}

        {(visit.status === 'scheduled' || visit.status === 'in_progress') && mode === 'view' && (
          <VisitActions vm={vm} tz={tz} />
        )}
        {visit.status !== 'scheduled' && visit.status !== 'in_progress' && <TouchSummary vm={vm} />}

        {editable && mode === 'view' && (
          <div className="flex gap-2">
            <Button
              variant="soft"
              className="flex-1"
              icon={<CalendarClock size={20} />}
              onClick={() => setMode('reschedule')}
            >
              Cambiar hora
            </Button>
            <Button variant="outline" className="flex-1" onClick={() => setMode('not_done')}>
              No se realizó
            </Button>
          </div>
        )}

        {editable && mode === 'reschedule' && (
          <div className="space-y-4">
            <div>
              <label htmlFor="visit-day" className="mb-1.5 block text-sm font-semibold">
                Día
              </label>
              <input
                id="visit-day"
                type="date"
                value={day}
                onChange={(e) => {
                  if (e.target.value) {
                    setDay(e.target.value)
                    setTime(null)
                  }
                }}
                className="min-h-12 w-full rounded-control border border-line bg-white px-3.5 text-base focus:border-brand"
              />
            </div>
            <div>
              <p className="mb-1.5 text-sm font-semibold">Hora</p>
              <TimePicker day={day} tz={tz} value={time} onChange={setTime} />
            </div>
            <Button variant="ghost" block onClick={() => setMode('view')}>
              Cancelar
            </Button>
          </div>
        )}

        {editable && mode === 'not_done' && (
          <div className="space-y-3">
            <p className="text-sm font-semibold">¿Qué pasó?</p>
            <div className="flex flex-col gap-2">
              {NOT_DONE_REASONS.map((reason) => (
                <Chip key={reason} className="text-left" onClick={() => void notDone(reason)}>
                  {NOT_DONE_LABEL[reason]}
                </Chip>
              ))}
            </div>
            <Button variant="ghost" block onClick={() => setMode('view')}>
              Volver
            </Button>
          </div>
        )}
      </div>
    </Sheet>
  )
}
