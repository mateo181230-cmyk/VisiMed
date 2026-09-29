import clsx from 'clsx'
import { ChevronRight, ClipboardList } from 'lucide-react'
import { useState } from 'react'
import { ScreenHeader } from '../../components/ScreenHeader'
import { SyncPill } from '../../components/SyncPill'
import { Card, SectionTitle, Skeleton } from '../../components/ui'
import { formatTime } from '../../lib/time'
import { ReportSheet, pendingMessage } from './ReportSheet'
import { reportSnippet } from './labels'
import { type HistoryItem, useHistory } from './useHistory'

type Tone = 'brand' | 'ok' | 'warn' | 'muted'

const TONES: Record<Tone, string> = {
  brand: 'bg-brand-50 text-brand',
  ok: 'bg-ok-50 text-ok',
  warn: 'bg-warn-50 text-warn',
  muted: 'bg-line/70 text-muted',
}

/** El estado de la visita en una palabra corta. */
export function statusPill(item: HistoryItem): { text: string; tone: Tone } {
  const { status } = item.vm.visit
  if (item.report?.status === 'confirmed' || status === 'confirmed') return { text: 'Confirmada', tone: 'ok' }
  if (item.report?.status === 'ready' || status === 'ready') return { text: 'Por confirmar', tone: 'brand' }
  switch (status) {
    case 'in_call':
      return { text: 'Llamando…', tone: 'brand' }
    case 'processing':
      return { text: 'Procesando', tone: 'muted' }
    case 'finished':
      return item.vm.visit.call?.next_at
        ? { text: 'Te llamamos de nuevo', tone: 'warn' }
        : { text: 'Pendiente de llamada', tone: 'muted' }
    case 'no_interview':
      return { text: 'Sin resumen', tone: 'warn' }
    case 'error':
      return { text: 'Error', tone: 'warn' }
    case 'not_done':
      return { text: 'No se realizó', tone: 'muted' }
    default:
      return { text: status, tone: 'muted' }
  }
}

function HistoryRow({ item, tz, onOpen }: { item: HistoryItem; tz: string; onOpen: () => void }) {
  const { vm, report } = item
  const pill = statusPill(item)
  const detail = report ? reportSnippet(report) : (pendingMessage(item, tz)?.text ?? '')
  return (
    <button type="button" onClick={onOpen} className="flex min-h-[76px] w-full items-center gap-3 px-4 py-3 text-left active:bg-canvas">
      <span className="w-[78px] shrink-0 text-[15px] font-semibold whitespace-nowrap tabular-nums">{formatTime(item.at, tz)}</span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="truncate font-semibold">{vm.doctor?.full_name ?? 'Médico'}</span>
        </span>
        <span className="mt-0.5 line-clamp-2 block text-sm text-muted">{detail}</span>
        <span className={clsx('mt-1.5 inline-block rounded-md px-2 py-0.5 text-xs font-bold', TONES[pill.tone])}>
          {pill.text}
        </span>
      </span>
      <ChevronRight size={20} className="shrink-0 text-muted" aria-hidden />
    </button>
  )
}

/** Historial: el resumen de cada visita, por día, con lo que falta confirmar arriba. */
export function HistoryScreen() {
  const { loading, tz, groups, toConfirm } = useHistory()
  const [openId, setOpenId] = useState<string | null>(null)
  const opened = groups.flatMap((g) => g.items).find((i) => i.vm.visit.id === openId) ?? null

  return (
    <>
      <ScreenHeader
        title="Historial"
        subtitle={toConfirm > 0 ? `${toConfirm} por confirmar` : 'Todo al día'}
        right={<SyncPill />}
      />
      <div className="space-y-6 px-5 pb-6">
        {loading ? (
          <div className="space-y-4">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-40" />
          </div>
        ) : groups.length === 0 ? (
          <Card className="p-6 text-center">
            <ClipboardList size={36} className="mx-auto text-muted" aria-hidden />
            <p className="mt-3 text-lg font-bold">Aún no hay visitas en tu historial</p>
            <p className="mt-1 text-muted">
              Cuando termines una visita, aquí verás el resumen que armamos con tu llamada, listo para confirmar.
            </p>
          </Card>
        ) : (
          groups.map((group) => (
            <section key={group.day} className="space-y-2">
              <SectionTitle>{group.title}</SectionTitle>
              <Card className="divide-y divide-line overflow-hidden">
                {group.items.map((item) => (
                  <HistoryRow
                    key={item.vm.visit.id}
                    item={item}
                    tz={tz}
                    onOpen={() => setOpenId(item.vm.visit.id)}
                  />
                ))}
              </Card>
            </section>
          ))
        )}
      </div>
      <ReportSheet item={opened} tz={tz} onClose={() => setOpenId(null)} />
    </>
  )
}
