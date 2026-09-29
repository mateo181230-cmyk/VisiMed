import { Check, MapPin, RefreshCw } from 'lucide-react'
import { useRef, useState } from 'react'
import { useToast } from '../../components/Toast'
import { Button, Notice } from '../../components/ui'
import type { GeoResult } from '../../db/db'
import { dateKey, todayKey } from '../../lib/time'
import { useNow } from '../../lib/useNow'
import { RETRYABLE_GEO, geoOf } from '../../sync/overlay'
import type { TouchMoment } from '../../sync/events'
import type { VisitVM } from '../agenda/useAgenda'
import { etiquetaGeo } from '../geo/etiquetas'
import { formatDuration, formatElapsed } from './format'
import { RETRY_WINDOW_MS, recordTouch, retryLocation, toWireLocation } from './recordTouch'

/** Resultado de la ubicación de un toque, con «Reintentar ubicación» si no sirvió y aún hay tiempo. */
function GeoLine({
  vm,
  moment,
  geo,
  touchedAt,
  now,
  prefix,
}: {
  vm: VisitVM
  moment: TouchMoment
  geo: GeoResult | null | undefined
  touchedAt: string | null | undefined
  now: Date
  prefix?: string
}) {
  const toast = useToast()
  const [retrying, setRetrying] = useState(false)

  // Mientras se toma la lectura, el evento aún no trae ubicación: no mostrar «Sin GPS» todavía.
  if (vm.capturing === moment) return <Notice tone="info">Buscando tu ubicación…</Notice>
  if (!geo) return null

  const { texto, tono } = etiquetaGeo(geo)
  const withinWindow = !!touchedAt && now.getTime() - Date.parse(touchedAt) <= RETRY_WINDOW_MS
  const canRetry = RETRYABLE_GEO.has(geo.state) && withinWindow && vm.capturing === null

  async function retry(): Promise<void> {
    setRetrying(true)
    try {
      const u = await retryLocation(moment, vm.visit.id)
      toast.show(u.fuente === 'ninguna' ? 'No pudimos tomar tu ubicación. Intenta de nuevo.' : 'Ubicación actualizada')
    } finally {
      setRetrying(false)
    }
  }

  return (
    <div className="space-y-1.5">
      <Notice tone={tono}>
        {prefix && <span className="font-semibold">{prefix} · </span>}
        {retrying ? 'Buscando tu ubicación…' : texto}
      </Notice>
      {canRetry && !retrying && (
        <Button variant="soft" block icon={<RefreshCw size={18} />} onClick={() => void retry()}>
          Reintentar ubicación
        </Button>
      )}
    </div>
  )
}

/**
 * Llegué / Terminé (doc 02 T4.2, T4.3): el botón grande de la visita.
 *  · Agendada de hoy → «Llegué».
 *  · En visita → cronómetro, cómo quedó la ubicación de la llegada y «Terminé».
 */
export function VisitActions({ vm, tz }: { vm: VisitVM; tz: string }) {
  const { visit } = vm
  const toast = useToast()
  const now = useNow(1000)
  const busy = useRef(false)

  async function touch(moment: TouchMoment): Promise<void> {
    if (busy.current) return
    busy.current = true
    navigator.vibrate?.(30) // confirmación táctil donde exista (Android)
    try {
      const u = await recordTouch(moment, visit.id)
      const geo = geoOf(toWireLocation(u), vm.institution)
      const { texto } = etiquetaGeo(geo)
      if (moment === 'arrival') {
        toast.show(`Llegada registrada · ${texto}`)
      } else {
        const since = visit.arrived_at ? formatDuration(Date.now() - Date.parse(visit.arrived_at)) : null
        toast.show(`Visita terminada${since ? ` · ${since}` : ''} · ${texto}`)
      }
    } finally {
      busy.current = false
    }
  }

  if (visit.status === 'scheduled') {
    // Solo se llega a una visita de hoy; una agendada para otro día se abre y se reprograma.
    if (dateKey(visit.scheduled_at, tz) !== todayKey(tz, now)) return null
    return (
      <Button size="lg" block icon={<MapPin size={22} />} onClick={() => void touch('arrival')}>
        Llegué
      </Button>
    )
  }

  if (visit.status === 'in_progress') {
    return (
      <div className="space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-[15px] font-semibold text-muted">En visita</span>
          <span className="text-[30px] leading-none font-extrabold tracking-tight tabular-nums" role="timer">
            {visit.arrived_at ? formatElapsed(now.getTime() - Date.parse(visit.arrived_at)) : '--:--'}
          </span>
        </div>
        <GeoLine vm={vm} moment="arrival" geo={visit.arrival_geo} touchedAt={visit.arrived_at} now={now} />
        <Button size="lg" block icon={<Check size={22} />} onClick={() => void touch('finish')}>
          Terminé
        </Button>
      </div>
    )
  }

  return null
}

/** Resumen de una visita ya terminada: duración y cómo quedó la ubicación de cada toque. */
export function TouchSummary({ vm }: { vm: VisitVM }) {
  const { visit } = vm
  const now = useNow(1000)
  if (!visit.arrived_at && !visit.finished_at) return null
  const duration =
    visit.arrived_at && visit.finished_at
      ? formatDuration(Date.parse(visit.finished_at) - Date.parse(visit.arrived_at))
      : null
  return (
    <div className="space-y-2">
      {duration && (
        <p className="text-[15px] text-muted">
          Duración de la visita: <strong className="text-ink">{duration}</strong>
        </p>
      )}
      {!visit.arrived_at && <Notice tone="warn">Sin hora de llegada: se tocó Terminé sin Llegué.</Notice>}
      <GeoLine
        vm={vm}
        moment="arrival"
        geo={visit.arrival_geo}
        touchedAt={visit.arrived_at}
        now={now}
        prefix="Llegada"
      />
      <GeoLine vm={vm} moment="finish" geo={visit.finish_geo} touchedAt={visit.finished_at} now={now} prefix="Salida" />
    </div>
  )
}
