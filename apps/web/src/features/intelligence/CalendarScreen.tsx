import { CalendarDays, ChevronLeft, ChevronRight, Clock3, MapPin, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { addDays, dayNumber, format12, isDateKey, weekStart } from '../../lib/time'
import { useIntelligence } from './IntelligenceProvider'
import { EmptyState, IntelButton, Modal, ScheduleDialog } from './components'
import { dayName, endTime, shortDate } from './model'
import type { CalendarVisit } from './types'

export function IntelligenceCalendar() {
  const { mode, visits, path, calendarPath, coreAgenda, removeVisit, doctors, today } = useIntelligence()
  const [params, setParams] = useSearchParams()
  const rawDay = params.get('fecha')
  const selectedDay = isDateKey(rawDay) ? rawDay : today
  const [planning, setPlanning] = useState(false)
  const [openedVisit, setOpenedVisit] = useState<CalendarVisit | null>(null)
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart(selectedDay), i))
  const visibleVisits = visits.filter((v) => v.day === selectedDay).sort((a, b) => a.time.localeCompare(b.time))
  const doctor = doctors.find((d) => d.id === openedVisit?.doctorId)
  const selectDay = (day: string) => setParams({ fecha: day })
  if (coreAgenda) return <Navigate to={calendarPath(selectedDay)} replace />
  return (
    <>
      <header className="intel-mobile-heading intel-mobile-heading--action">
        <div>
          <h1>Agenda</h1>
          <p>{mode === 'demo' ? 'Calendario de ejemplo.' : 'Visitas programadas en UNO.'}</p>
        </div>
        {mode !== 'empty' && (
          <button
            type="button"
            className="intel-icon-button"
            aria-label="Programar visita"
            onClick={() => setPlanning(true)}
          >
            <Plus size={24} />
          </button>
        )}
      </header>
      {mode === 'empty' ? (
        <EmptyState
          icon={CalendarDays}
          title="El calendario aún no está conectado"
          description="Explora el ejemplo para ver cómo programar una recomendación."
        />
      ) : (
        <>
          <div className="intel-calendar-week-navigation">
            <button
              type="button"
              className="intel-icon-button"
              aria-label="Día anterior"
              onClick={() => selectDay(addDays(selectedDay, -1))}
            >
              <ChevronLeft size={21} />
            </button>
            <strong>{shortDate(selectedDay)}</strong>
            <button
              type="button"
              className="intel-icon-button"
              aria-label="Día siguiente"
              onClick={() => selectDay(addDays(selectedDay, 1))}
            >
              <ChevronRight size={21} />
            </button>
          </div>
          <div className="intel-mobile-days" aria-label="Días de la semana">
            {days.map((day) => (
              <button
                type="button"
                key={day}
                aria-label={`Ver día ${shortDate(day)}`}
                aria-pressed={day === selectedDay}
                onClick={() => selectDay(day)}
              >
                <span>{dayName(day)}</span>
                <strong>{dayNumber(day)}</strong>
              </button>
            ))}
          </div>
          <p className="intel-mobile-list-count">
            {visibleVisits.length} {visibleVisits.length === 1 ? 'visita programada' : 'visitas programadas'}
          </p>
          {visibleVisits.length ? (
            <div className="intel-mobile-calendar-list">
              {visibleVisits.map((visit) => {
                const d = doctors.find((d) => d.id === visit.doctorId)
                if (!d) return null
                return (
                  <button
                    type="button"
                    key={visit.id}
                    aria-label={`${d.name} · ${format12(visit.time)}${visit.source === 'suggestion' ? ' · Desde una sugerencia' : ''}`}
                    onClick={() => setOpenedVisit(visit)}
                  >
                    <span className="intel-mobile-calendar-time">
                      {format12(visit.time)}
                      <small>{visit.duration} min</small>
                    </span>
                    <span className="intel-mobile-calendar-doctor">
                      <strong>{visit.title || d.name}</strong>
                      {visit.title && <small>{d.name}</small>}
                      <small>{d.institution}</small>
                    </span>
                    <ChevronRight size={18} />
                  </button>
                )
              })}
            </div>
          ) : (
            <div className="intel-mobile-calendar-empty">
              <h2>Un día sin visitas programadas</h2>
              <p>Revisa cuál podría ser tu siguiente visita.</p>
              <Link to={path()}>Ver recomendaciones</Link>
            </div>
          )}
        </>
      )}
      <ScheduleDialog
        open={planning}
        onClose={() => setPlanning(false)}
        initialDay={selectedDay < today ? today : selectedDay}
      />
      <Modal open={!!openedVisit} onClose={() => setOpenedVisit(null)} title="Visita planeada">
        {openedVisit && doctor && (
          <>
            <div className="intel-quick-plan-identity">
              <h3>{doctor.name}</h3>
              <p>{doctor.institution}</p>
            </div>
            <div className="intel-visit-details">
              <p>
                <Clock3 size={17} />
                {shortDate(openedVisit.day)} · {format12(openedVisit.time)} —{' '}
                {format12(endTime(openedVisit.time, openedVisit.duration))}
              </p>
              <p>
                <MapPin size={17} />
                {doctor.address}
              </p>
            </div>
            <p className="intel-small-note">
              {mode === 'demo' ? 'Calendario de ejemplo.' : 'Hora registrada en UNO; duración prevista de referencia.'}{' '}
              Coordina la cita con el consultorio.
            </p>
            <div className="intel-dialog-actions">
              {mode === 'demo' && openedVisit.source !== 'existing' && (
                <IntelButton
                  variant="quiet"
                  onClick={() => {
                    removeVisit(openedVisit.id)
                    setOpenedVisit(null)
                  }}
                >
                  <Trash2 size={16} />
                  Retirar del ejemplo
                </IntelButton>
              )}
              <Link
                className="intel-button intel-button--secondary"
                to={path(`medicos/${doctor.id}?linea=${openedVisit.line}`)}
              >
                Ver perfil
              </Link>
            </div>
          </>
        )}
      </Modal>
    </>
  )
}
