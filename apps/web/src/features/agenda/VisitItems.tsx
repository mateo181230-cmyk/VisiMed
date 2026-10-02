import clsx from 'clsx'
import { Building2, ChevronRight, CloudUpload, MapPin, Stethoscope, User } from 'lucide-react'
import type { ReactNode } from 'react'
import { Card } from '../../components/ui'
import { formatTime } from '../../lib/time'
import { NOT_DONE_LABEL, type VisitVM } from './useAgenda'
import { PreviousVisitReminder } from './PreviousVisitReminder'

const subtitle = (vm: VisitVM): string =>
  [vm.institution?.name, vm.doctor?.specialty].filter(Boolean).join(' · ') || 'Sin institución'

/** Etiquetas de las líneas de la visita (GASTRU, RESPI…). */
export function LineTags({ vm }: { vm: VisitVM }) {
  if (vm.lines.length === 0) return null
  return (
    <span className="flex flex-wrap gap-1.5">
      {vm.lines.map((l, i) => (
        <span
          key={l.id}
          className={clsx(
            'rounded-md px-2 py-0.5 text-xs font-bold tracking-wide',
            i === 0 ? 'bg-brand-50 text-brand' : 'bg-line/70 text-muted',
          )}
        >
          {l.name}
        </span>
      ))}
    </span>
  )
}

export function UnsentMark() {
  return (
    <span className="inline-flex items-center gap-1 text-xs font-semibold text-muted" title="Aún no se envía">
      <CloudUpload size={14} aria-hidden />
      <span className="sr-only">Aún no se envía</span>
    </span>
  )
}

/** Tarjeta grande de la visita actual o siguiente (pantalla Hoy). */
export function NextVisitCard({
  vm,
  tz,
  label,
  onOpen,
  children,
}: {
  vm: VisitVM
  tz: string
  label: string
  onOpen: () => void
  /** Acciones de la visita (Llegué / Terminé) bajo los datos. */
  children?: ReactNode
}) {
  const { visit, doctor, institution } = vm
  return (
    <Card className="p-5">
      <PreviousVisitReminder vm={vm} />
      <div className="flex items-center justify-between">
        <span className="inline-flex items-center gap-2 text-base font-bold">
          <span className="size-2.5 rounded-full bg-brand" aria-hidden />
          {label}
        </span>
        {vm.unsent && <UnsentMark />}
      </div>
      <p className="mt-2 text-[40px] leading-none font-extrabold tracking-tight">
        {formatTime(visit.scheduled_at, tz)}
      </p>
      <ul className="mt-4 space-y-2.5 text-base">
        <li className="flex items-center gap-3">
          <User size={20} className="shrink-0 text-muted" aria-hidden />
          <span className="font-semibold">{visit.title || doctor?.full_name || 'Médico'}</span>
        </li>
        {doctor?.specialty && (
          <li className="flex items-center gap-3">
            <Stethoscope size={20} className="shrink-0 text-muted" aria-hidden />
            {doctor.specialty}
          </li>
        )}
        {institution && (
          <li className="flex items-center gap-3">
            <Building2 size={20} className="shrink-0 text-muted" aria-hidden />
            {institution.name}
          </li>
        )}
        {institution?.address && (
          <li className="flex items-center gap-3">
            <MapPin size={20} className="shrink-0 text-muted" aria-hidden />
            {institution.address}
          </li>
        )}
      </ul>
      {children && <div className="mt-5">{children}</div>}
      <div className="mt-4 flex items-center justify-between gap-3">
        <LineTags vm={vm} />
        <button
          type="button"
          onClick={onOpen}
          className="-mr-1 inline-flex min-h-12 items-center gap-1 rounded-control px-3 font-semibold text-brand active:bg-brand-50"
        >
          Ver o cambiar
          <ChevronRight size={18} aria-hidden />
        </button>
      </div>
    </Card>
  )
}

/** Fila compacta: hora · médico · institución (listas «Después», «Por resolver», «Realizadas»). */
export function VisitRowItem({
  vm,
  tz,
  onOpen,
  tone = 'normal',
}: {
  vm: VisitVM
  tz: string
  onOpen: () => void
  tone?: 'normal' | 'warn' | 'muted'
}) {
  const { visit, doctor } = vm
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex min-h-16 w-full items-center gap-3 px-4 py-2.5 text-left active:bg-canvas"
    >
      <span className="w-[74px] shrink-0 text-[15px] font-semibold tabular-nums">
        {formatTime(visit.scheduled_at, tz)}
      </span>
      <span
        aria-hidden
        className={clsx(
          'size-2.5 shrink-0 rounded-full',
          tone === 'warn' ? 'bg-warn' : tone === 'muted' ? 'bg-line' : 'bg-brand',
        )}
      />
      <span className="min-w-0 flex-1">
        <span className={clsx('block truncate font-semibold', tone === 'muted' && 'text-muted')}>
          {visit.title || doctor?.full_name || 'Médico'}
        </span>
        <span className="block truncate text-sm text-muted">
          {visit.status === 'not_done'
            ? `No se realizó${visit.not_done_reason ? ` · ${NOT_DONE_LABEL[visit.not_done_reason] ?? ''}` : ''}`
            : subtitle(vm)}
        </span>
      </span>
      {vm.unsent && <UnsentMark />}
      <ChevronRight size={20} className="shrink-0 text-muted" aria-hidden />
    </button>
  )
}
