import clsx from 'clsx'
import { AlertTriangle, ArrowUpFromLine, Check, CloudOff, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useEngineState, useOnline, useOutboxCounts } from '../sync/SyncProvider'

/** Indicador discreto de sincronización: ✓ al día · ↑ n pendientes · ⚠ error (doc 02 T2.4 ST8). */
export function SyncPill() {
  const online = useOnline()
  const engine = useEngineState()
  const { pending, rejected, expired } = useOutboxCounts()

  let tone = 'bg-ok-50 text-ok'
  let icon = <Check size={14} strokeWidth={3} />
  let label = 'Al día'

  if (rejected + expired > 0 || engine === 'auth') {
    tone = 'bg-warn-50 text-warn'
    icon = <AlertTriangle size={14} />
    label = engine === 'auth' ? 'Ingresa de nuevo' : `${rejected + expired} con problema`
  } else if (!online || engine === 'offline') {
    tone = 'bg-line/70 text-muted'
    icon = <CloudOff size={14} />
    label = pending > 0 ? `Sin conexión · ${pending} por enviar` : 'Sin conexión'
  } else if (pending > 0) {
    tone = 'bg-brand-50 text-brand'
    icon = <ArrowUpFromLine size={14} />
    label = `${pending} por enviar`
  } else if (engine === 'syncing') {
    icon = <RefreshCw size={14} className="animate-spin" />
    label = 'Sincronizando'
  } else if (engine === 'error') {
    tone = 'bg-warn-50 text-warn'
    icon = <AlertTriangle size={14} />
    label = 'Reintentando'
  }

  // Cuando todo está bien (o sincronizando) es solo un ícono: el encabezado queda limpio y el
  // texto aparece únicamente cuando hay algo que decir.
  const compact = label === 'Al día' || label === 'Sincronizando'

  return (
    <Link
      to="/mas/pendientes"
      aria-label={`Sincronización: ${label}`}
      title={label}
      className={clsx(
        'inline-flex items-center justify-center rounded-full text-[13px] font-semibold',
        compact ? 'size-9' : 'min-h-9 gap-1.5 px-3',
        tone,
      )}
    >
      {icon}
      {!compact && label}
    </Link>
  )
}
