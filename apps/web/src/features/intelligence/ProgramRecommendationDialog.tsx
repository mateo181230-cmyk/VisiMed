import { CalendarDays, CalendarPlus, ChevronDown } from 'lucide-react'
import { useEffect, useState } from 'react'
import { format12 } from '../../lib/time'
import { IntelButton, Modal } from './components'
import { useIntelligence } from './IntelligenceProvider'
import { shortDate } from './model'
import type { Recommendation } from './types'

export function ProgramRecommendationDialog({
  recommendation,
  onClose,
  onScheduled,
}: {
  recommendation: Recommendation | null
  onClose: () => void
  onScheduled?: (name: string, day: string) => void
}) {
  const { addVisit, doctors, today, mode } = useIntelligence()
  const [day, setDay] = useState('')
  const [time, setTime] = useState('')
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (!recommendation) return
    setDay(recommendation.day)
    setTime(recommendation.time)
    setEditing(false)
    setError(null)
  }, [recommendation])
  const doctor = doctors.find((d) => d.id === recommendation?.doctorId)
  return (
    <Modal open={!!recommendation} onClose={onClose} title="Programar visita">
      {recommendation && doctor && (
        <form
          className="intel-quick-plan"
          onSubmit={async (e) => {
            e.preventDefault()
            if (saving) return
            setSaving(true)
            let message: string | null
            try {
              message = await addVisit({
                id: `demo-${recommendation.id}`,
                doctorId: doctor.id,
                line: recommendation.line,
                day,
                time,
                duration: recommendation.duration,
                source: 'suggestion',
                recommendationId: recommendation.id,
              })
            } catch {
              message = 'No se pudo guardar la visita. Intenta de nuevo.'
            }
            setSaving(false)
            setError(message)
            if (message) setEditing(true)
            else {
              onScheduled?.(doctor.name, day)
              onClose()
            }
          }}
        >
          <div className="intel-quick-plan-identity">
            <h3>{doctor.name}</h3>
            <p>{doctor.institution}</p>
          </div>
          <div className="intel-quick-plan-slot">
            <CalendarDays size={20} />
            <span>
              <strong>
                {day && shortDate(day)} · {time && format12(time)}
              </strong>
              <small>{recommendation.duration} minutos · Hora de Bogotá</small>
            </span>
          </div>
          <button
            type="button"
            className="intel-change-slot"
            aria-expanded={editing}
            onClick={() => setEditing(!editing)}
          >
            Cambiar horario <ChevronDown size={16} />
          </button>
          {editing && (
            <div className="intel-form intel-form-grid">
              <label>
                Fecha
                <input type="date" required min={today} value={day} onChange={(e) => setDay(e.target.value)} />
              </label>
              <label>
                Hora
                <input
                  type="time"
                  required
                  min="08:00"
                  max="17:30"
                  step="900"
                  value={time}
                  onChange={(e) => setTime(e.target.value)}
                />
              </label>
            </div>
          )}
          <p className="intel-small-note">
            {mode === 'demo'
              ? 'Se guarda en el calendario de ejemplo.'
              : 'Se guarda en tu agenda y se sincroniza con el servidor.'}{' '}
            Coordina la cita con el consultorio.
          </p>
          {error && (
            <p className="intel-form-error" role="alert">
              {error}
            </p>
          )}
          <IntelButton type="submit" disabled={saving}>
            <CalendarPlus size={18} /> Programar visita
          </IntelButton>
        </form>
      )}
    </Modal>
  )
}
