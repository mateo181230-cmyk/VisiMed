import clsx from 'clsx'
import { ArrowRight, CalendarPlus, Lightbulb, Stethoscope, X, type LucideIcon } from 'lucide-react'
import { useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { initials } from '../../lib/text'
import { useIntelligence } from './IntelligenceProvider'
import { LINE_NAMES, type DoctorProfile, type LineCode, type Recommendation } from './types'

export function IntelButton({
  children,
  className,
  variant = 'primary',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'quiet'
}) {
  return (
    <button type="button" className={clsx('intel-button', `intel-button--${variant}`, className)} {...props}>
      {children}
    </button>
  )
}

export function Avatar({ doctor, small = false }: { doctor: DoctorProfile; small?: boolean }) {
  return (
    <span aria-hidden className={clsx('intel-avatar', `intel-avatar--${doctor.color}`, small && 'intel-avatar--small')}>
      {initials(doctor.name.replace(/^(Dra?\.)\s*/, ''))}
    </span>
  )
}

export function LineBadge({ line }: { line: LineCode }) {
  return (
    <span className={`intel-line intel-line--${line.toLowerCase()}`}>
      <span aria-hidden />
      {LINE_NAMES[line]}
    </span>
  )
}

export function RepresentativeName({ id }: { id: string }) {
  const { representatives } = useIntelligence()
  return <>{representatives.find((r) => r.id === id)?.name ?? 'Visitador'}</>
}

export function EmptyState({
  icon: Icon = Stethoscope,
  title,
  description,
  action = true,
}: {
  icon?: LucideIcon
  title: string
  description: string
  action?: boolean
}) {
  const { setMode } = useIntelligence()
  return (
    <div className="intel-empty">
      <span className="intel-empty-icon">
        <Icon size={28} />
      </span>
      <h2>{title}</h2>
      <p>{description}</p>
      {action && (
        <IntelButton onClick={() => setMode('demo')}>
          Explorar con datos de ejemplo <ArrowRight size={17} />
        </IntelButton>
      )}
    </div>
  )
}

export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
}) {
  const { mode } = useIntelligence()
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (!open) return
    const dialog = ref.current
    if (!dialog) return
    if (typeof dialog.showModal === 'function') dialog.showModal()
    else dialog.setAttribute('open', '')
    const before = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      if (typeof dialog.close === 'function' && dialog.open) dialog.close()
      document.body.style.overflow = before
    }
  }, [open])
  if (!open) return null
  return (
    <dialog
      ref={ref}
      className="intel-dialog"
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="intel-dialog-content">
        <header>
          <div>
            <p className="intel-eyebrow">{mode === 'demo' ? 'Demostración' : 'UNO Visitas'}</p>
            <h2>{title}</h2>
          </div>
          <button type="button" className="intel-icon-button" aria-label="Cerrar ventana" onClick={onClose}>
            <X size={21} />
          </button>
        </header>
        {children}
      </div>
    </dialog>
  )
}

export function ScheduleDialog({
  open,
  onClose,
  doctorId,
  recommendation,
  initialDay,
  initialLine,
}: {
  open: boolean
  onClose: () => void
  doctorId?: string
  recommendation?: Recommendation
  initialDay?: string
  initialLine?: LineCode
}) {
  const { doctors, addVisit, today, mode } = useIntelligence()
  const [picked, setPicked] = useState(doctorId ?? '')
  const [line, setLine] = useState<LineCode>(recommendation?.line ?? 'GASTRU')
  const [day, setDay] = useState(initialDay ?? recommendation?.day ?? today)
  const [time, setTime] = useState(recommendation?.time ?? '10:00')
  const [duration, setDuration] = useState(30)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (!open) return
    const doctor = doctors.find((d) => d.id === (recommendation?.doctorId ?? doctorId))
    setPicked(doctor?.id ?? '')
    setLine(recommendation?.line ?? initialLine ?? doctor?.profiles[0]?.line ?? 'GASTRU')
    setDay(initialDay ?? recommendation?.day ?? today)
    setTime(recommendation?.time ?? '10:00')
    setDuration(recommendation?.duration ?? 30)
    setError(null)
  }, [open, doctorId, initialDay, initialLine, recommendation])
  const doctor = doctors.find((d) => d.id === picked)
  return (
    <Modal open={open} onClose={onClose} title="Planear una visita">
      <form
        className="intel-form"
        onSubmit={async (event) => {
          event.preventDefault()
          if (saving) return
          setSaving(true)
          let message: string | null
          try {
            message = await addVisit({
              id: recommendation ? `demo-${recommendation.id}` : `demo-manual-${crypto.randomUUID()}`,
              doctorId: picked,
              line,
              day,
              time,
              duration,
              source: recommendation ? 'suggestion' : 'manual',
              recommendationId: recommendation?.id,
            })
          } catch {
            message = 'No se pudo guardar la visita. Intenta de nuevo.'
          }
          setSaving(false)
          setError(message)
          if (!message) onClose()
        }}
      >
        <label>
          Médico
          <select
            required
            value={picked}
            onChange={(e) => {
              setPicked(e.target.value)
              const d = doctors.find((d) => d.id === e.target.value)
              setLine(d?.profiles[0]?.line ?? 'GASTRU')
            }}
            disabled={!!recommendation}
          >
            <option value="">Seleccionar médico</option>
            {doctors.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        {doctor && (
          <div className="intel-form-context">
            <Stethoscope size={17} />
            <div>
              <strong>{doctor.institution}</strong>
              <span>
                Visitador: <RepresentativeName id={doctor.representativeId} />
              </span>
            </div>
          </div>
        )}
        <label>
          Línea
          <select value={line} onChange={(e) => setLine(e.target.value as LineCode)} disabled={!!recommendation}>
            {Object.entries(LINE_NAMES).map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <div className="intel-form-grid">
          <label>
            Fecha
            <input type="date" required min={today} value={day} onChange={(e) => setDay(e.target.value)} />
          </label>
          <label>
            Hora · Bogotá
            <input
              type="time"
              required
              min="08:00"
              max="17:45"
              step="900"
              value={time}
              onChange={(e) => setTime(e.target.value)}
            />
          </label>
        </div>
        <label>
          Duración
          <select value={duration} onChange={(e) => setDuration(Number(e.target.value))}>
            {[15, 30, 45, 60].map((n) => (
              <option key={n} value={n}>
                {n} minutos
              </option>
            ))}
          </select>
        </label>
        <p className="intel-callout">
          <Lightbulb size={17} />
          <span>
            {mode === 'demo' ? 'Se agrega al calendario de ejemplo.' : 'Se agrega a tu agenda.'} La hora propuesta debe
            coordinarse con el consultorio; no confirma una cita con el médico.
          </span>
        </p>
        {error && (
          <p className="intel-form-error" role="alert">
            {error}
          </p>
        )}
        <div className="intel-dialog-actions">
          <IntelButton variant="secondary" onClick={onClose}>
            Cancelar
          </IntelButton>
          <IntelButton type="submit" disabled={!picked || saving}>
            <CalendarPlus size={17} />
            Agregar al calendario
          </IntelButton>
        </div>
      </form>
    </Modal>
  )
}
