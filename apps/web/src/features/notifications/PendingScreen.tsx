import { useLiveQuery } from 'dexie-react-hooks'
import { ChevronLeft, RefreshCw, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ScreenHeader } from '../../components/ScreenHeader'
import { Button, Card, Notice } from '../../components/ui'
import { type OutboxRow, db } from '../../db/db'
import { DEFAULT_TZ, formatTime } from '../../lib/time'
import { retryExpired } from '../../sync/outbox'
import { useEngine, useEngineState, useOnline } from '../../sync/SyncProvider'

const TYPE_LABEL: Record<string, string> = {
  doctor_created: 'Nuevo médico',
  visit_scheduled: 'Visita agendada',
  visit_rescheduled: 'Cambio de hora',
  visit_not_done: 'Visita «No se realizó»',
}

const STATUS_LABEL: Record<string, string> = {
  pending: 'En cola',
  sending: 'Enviando…',
  confirmed: 'Enviado',
  rejected: 'Rechazado',
  expired: 'Vencido (24 h sin poder enviar)',
}

const REASON_LABEL: Record<string, string> = {
  unknown_doctor: 'El médico no está en tu panel.',
  unknown_visit: 'La visita no existe.',
  unknown_line: 'La línea no existe.',
  visit_not_editable: 'La visita ya no se puede cambiar.',
  visit_id_conflict: 'Esa visita ya existe con otros datos.',
  invalid_time: 'La fecha u hora no es válida.',
  invalid_payload: 'Faltan datos o son inválidos.',
  unknown_event_type: 'Tu app está desactualizada.',
  event_id_conflict: 'Conflicto de identificador.',
}

/** Pendientes (doc 01 §8.2, S9): qué falta subir, qué salió mal y cómo reintentar. */
export function PendingScreen() {
  const engine = useEngine()
  const state = useEngineState()
  const online = useOnline()
  const rows = useLiveQuery(() => db.outbox.orderBy('seq').reverse().toArray(), [], [] as OutboxRow[])
  const tz = useLiveQuery(async () => (await db.meta.get('timezone'))?.value as string | undefined, [], 'America/Bogota')

  const open = rows.filter((r) => r.status !== 'confirmed')
  const hasExpired = rows.some((r) => r.status === 'expired')

  async function retry(): Promise<void> {
    await retryExpired()
    await engine.run(true)
  }

  return (
    <>
      <div className="px-2 pt-[calc(8px+var(--safe-top))]">
        <Link
          to="/mas"
          className="inline-flex min-h-12 items-center gap-1 rounded-control px-2 font-semibold text-brand active:bg-brand-50"
        >
          <ChevronLeft size={22} /> Más
        </Link>
      </div>
      <ScreenHeader title="Pendientes" subtitle="Lo que falta enviar al servidor" />
      <div className="space-y-4 px-5 pb-8">
        {!online && <Notice tone="info">Sin conexión. Se enviará solo cuando vuelva la señal; no tienes que hacer nada.</Notice>}
        {state === 'auth' && (
          <Notice tone="warn">
            Tu sesión venció. <Link to="/login" className="font-bold underline">Ingresa de nuevo</Link>: tus cambios se conservan.
          </Notice>
        )}

        {open.length === 0 ? (
          <Card className="p-6 text-center">
            <p className="text-lg font-bold">Todo está al día ✓</p>
            <p className="mt-1 text-muted">No hay nada pendiente de enviar.</p>
          </Card>
        ) : (
          <Card className="divide-y divide-line overflow-hidden">
            {open.map((r) => (
              <div key={r.seq} className="flex items-start justify-between gap-3 px-4 py-3.5">
                <div className="min-w-0">
                  <p className="font-semibold">{TYPE_LABEL[r.type] ?? r.type}</p>
                  <p className="text-sm text-muted">
                    {formatTime(r.device_ts, tz ?? DEFAULT_TZ)} · {STATUS_LABEL[r.status] ?? r.status}
                    {r.attempts > 0 && r.status === 'pending' ? ` · ${r.attempts} ${r.attempts === 1 ? 'intento' : 'intentos'}` : ''}
                  </p>
                  {r.status === 'rejected' && (
                    <p className="mt-1 text-sm text-danger">{REASON_LABEL[r.reason ?? ''] ?? r.reason ?? 'El servidor no lo aceptó.'}</p>
                  )}
                </div>
                {r.status === 'rejected' && (
                  <button
                    type="button"
                    aria-label="Descartar"
                    onClick={() => void db.outbox.delete(r.seq!)}
                    className="grid size-11 shrink-0 place-items-center rounded-full text-muted active:bg-canvas"
                  >
                    <Trash2 size={20} />
                  </button>
                )}
              </div>
            ))}
          </Card>
        )}

        {open.length > 0 && (
          <Button
            block
            size="lg"
            variant={hasExpired ? 'primary' : 'soft'}
            icon={<RefreshCw size={20} />}
            disabled={state === 'syncing'}
            onClick={() => void retry()}
          >
            {state === 'syncing' ? 'Enviando…' : 'Reintentar ahora'}
          </Button>
        )}
      </div>
    </>
  )
}
