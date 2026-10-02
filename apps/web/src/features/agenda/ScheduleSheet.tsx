import { ChevronRight, Plus, Search, User } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Sheet } from '../../components/Sheet'
import { useToast } from '../../components/Toast'
import { Button, Chip, Notice } from '../../components/ui'
import { newId } from '../../lib/ids'
import { matches } from '../../lib/text'
import { formatTime, localToUtc, todayKey } from '../../lib/time'
import { visitScheduled } from '../../sync/events'
import { enqueue } from '../../sync/outbox'
import { NewDoctorForm } from './NewDoctorForm'
import { TimePicker } from './TimePicker'
import type { Agenda } from './useAgenda'

interface Props {
  open: boolean
  onClose: () => void
  /** Día local preseleccionado (``YYYY-MM-DD``). */
  initialDay: string
  agenda: Agenda
}

interface Picked {
  id: string
  name: string
  defaultLineId: string | null
}

/**
 * Agendar una visita (doc 01 §8.3, S7; doc 02 T3.2). Con un médico reciente son 3 toques:
 * médico → hora → Guardar. Funciona sin red: solo escribe en la cola local.
 */
export function ScheduleSheet({ open, onClose, initialDay, agenda }: Props) {
  const toast = useToast()
  const [picked, setPicked] = useState<Picked | null>(null)
  const [creating, setCreating] = useState(false)
  const [query, setQuery] = useState('')
  const [day, setDay] = useState(initialDay)
  const [time, setTime] = useState<string | null>(null)
  const [lineIds, setLineIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setPicked(null)
    setCreating(false)
    setQuery('')
    setDay(initialDay)
    setTime(null)
    setLineIds([])
    setBusy(false)
  }, [open, initialDay])

  const activeLines = agenda.lines.filter((l) => l.active)

  // Recientes primero: el médico con la visita más cercana en el tiempo (pasada o futura).
  const doctors = useMemo(() => {
    const lastTouch = new Map<string, number>()
    for (const v of agenda.visits) {
      lastTouch.set(v.doctor_id, Math.max(lastTouch.get(v.doctor_id) ?? 0, Date.parse(v.updated_at) || 0))
    }
    const institutionName = new Map(agenda.institutions.map((i) => [i.id, i.name]))
    return [...agenda.doctors]
      .filter((d) => matches(`${d.full_name} ${institutionName.get(d.institution_id ?? '') ?? ''}`, query))
      .sort(
        (a, b) =>
          (lastTouch.get(b.id) ?? 0) - (lastTouch.get(a.id) ?? 0) || a.full_name.localeCompare(b.full_name, 'es'),
      )
  }, [agenda.doctors, agenda.visits, agenda.institutions, query])

  function pick(d: Picked): void {
    setPicked(d)
    setCreating(false)
    setLineIds(d.defaultLineId ? [d.defaultLineId] : [])
  }

  function toggleLine(id: string): void {
    setLineIds((cur) => {
      if (cur.includes(id)) return cur.length > 1 ? cur.filter((x) => x !== id) : cur
      return cur.length >= 2 ? [cur[0]!, id] : [...cur, id]
    })
  }

  const conflict = useMemo(() => {
    if (!time) return false
    const start = localToUtc(day, time, agenda.tz).getTime()
    return agenda.visits.some((v) => v.status === 'scheduled' && Math.abs(Date.parse(v.scheduled_at) - start) < 60_000)
  }, [agenda.visits, agenda.tz, day, time])

  async function save(): Promise<void> {
    if (!picked || !time || lineIds.length === 0 || busy) return
    setBusy(true)
    const when = localToUtc(day, time, agenda.tz)
    await enqueue(
      visitScheduled(newId(), {
        doctor_id: picked.id,
        line_ids: lineIds,
        scheduled_at: when.toISOString(),
        planned_by: 'rep',
      }),
    )
    toast.show(`Visita agendada · ${formatTime(when, agenda.tz)}`)
    onClose()
  }

  const canSave = !!picked && !!time && lineIds.length > 0 && !busy
  const institutionOf = (id: string | null): string | undefined => agenda.institutions.find((i) => i.id === id)?.name

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={creating ? 'Nuevo médico' : 'Programar visita'}
      footer={
        creating ? undefined : (
          <Button size="lg" block disabled={!canSave} onClick={() => void save()}>
            Guardar
          </Button>
        )
      }
    >
      {creating ? (
        <NewDoctorForm
          agenda={agenda}
          defaultName={query}
          onCancel={() => setCreating(false)}
          onCreated={(d) => pick({ id: d.id, name: d.name, defaultLineId: d.lineId })}
        />
      ) : (
        <div className="space-y-6 pt-1">
          {/* 1 · Médico */}
          <section aria-labelledby="sec-medico">
            <h3 id="sec-medico" className="mb-2 text-sm font-semibold">
              Médico
            </h3>
            {picked ? (
              <div className="flex items-center justify-between gap-3 rounded-control border border-brand bg-brand-50 px-3.5 py-3">
                <span className="flex min-w-0 items-center gap-2.5 font-semibold text-navy">
                  <User size={20} className="shrink-0" />
                  <span className="truncate">{picked.name}</span>
                </span>
                <button
                  type="button"
                  onClick={() => setPicked(null)}
                  className="min-h-10 shrink-0 px-2 text-sm font-semibold text-brand"
                >
                  Cambiar
                </button>
              </div>
            ) : (
              <>
                <div className="relative">
                  <Search
                    size={18}
                    className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-muted"
                  />
                  <input
                    type="search"
                    inputMode="search"
                    autoComplete="off"
                    placeholder="Buscar médico"
                    aria-label="Buscar médico"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    className="min-h-12 w-full rounded-control border border-line bg-white pr-3 pl-10 text-base focus:border-brand"
                  />
                </div>
                {!query && doctors.length > 0 && (
                  <p className="mt-3 mb-1 text-xs font-semibold tracking-wide text-muted uppercase">Recientes</p>
                )}
                <ul className="mt-1 divide-y divide-line">
                  {doctors.slice(0, 30).map((d) => (
                    <li key={d.id}>
                      <button
                        type="button"
                        onClick={() => pick({ id: d.id, name: d.full_name, defaultLineId: d.default_line_id })}
                        className="flex min-h-14 w-full items-center justify-between gap-3 py-2 text-left active:bg-canvas"
                      >
                        <span className="min-w-0">
                          <span className="block truncate font-semibold">{d.full_name}</span>
                          <span className="block truncate text-sm text-muted">
                            {[institutionOf(d.institution_id), d.specialty].filter(Boolean).join(' · ') ||
                              'Sin institución'}
                          </span>
                        </span>
                        <ChevronRight size={20} className="shrink-0 text-muted" />
                      </button>
                    </li>
                  ))}
                </ul>
                {doctors.length === 0 && (
                  <p className="py-3 text-[15px] text-muted">
                    {agenda.doctors.length === 0
                      ? 'Aún no tienes médicos. Agrega el primero.'
                      : 'No encontramos a ese médico.'}
                  </p>
                )}
                <Button
                  variant="soft"
                  block
                  icon={<Plus size={20} />}
                  className="mt-2"
                  onClick={() => setCreating(true)}
                >
                  Nuevo médico
                </Button>
              </>
            )}
          </section>

          {picked && (
            <>
              {/* 2 · Día */}
              <section aria-labelledby="sec-dia">
                <h3 id="sec-dia" className="mb-2 text-sm font-semibold">
                  Día
                </h3>
                <input
                  type="date"
                  aria-label="Día de la visita"
                  value={day}
                  onChange={(e) => {
                    if (e.target.value) {
                      setDay(e.target.value)
                      setTime(null)
                    }
                  }}
                  className="min-h-12 w-full rounded-control border border-line bg-white px-3.5 text-base focus:border-brand"
                />
                {day === todayKey(agenda.tz) && <p className="mt-1.5 text-sm text-muted">Hoy</p>}
              </section>

              {/* 3 · Hora */}
              <section aria-labelledby="sec-hora">
                <h3 id="sec-hora" className="mb-2 text-sm font-semibold">
                  Hora
                </h3>
                <TimePicker day={day} tz={agenda.tz} value={time} onChange={setTime} />
                {conflict && (
                  <Notice tone="warn" className="mt-3">
                    Ya tienes una visita a esa hora. Puedes guardarla igual.
                  </Notice>
                )}
              </section>

              {/* 4 · Línea */}
              <section aria-labelledby="sec-linea">
                <h3 id="sec-linea" className="mb-2 text-sm font-semibold">
                  Línea
                </h3>
                <div className="flex flex-wrap gap-2" role="group" aria-label="Línea de la visita">
                  {activeLines.map((l) => (
                    <Chip key={l.id} selected={lineIds.includes(l.id)} onClick={() => toggleLine(l.id)}>
                      {l.name}
                    </Chip>
                  ))}
                </div>
                <p className="mt-1.5 text-sm text-muted">
                  La primera es la principal. Toca otra para sumar una segunda línea (máximo 2).
                </p>
              </section>
            </>
          )}
        </div>
      )}
    </Sheet>
  )
}
