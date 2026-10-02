import { BrainCircuit, CalendarDays, ChevronRight, Layers3, SlidersHorizontal, Stethoscope } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { useIntelligence } from './IntelligenceProvider'
import { MobileAccordion } from './MobileAccordion'

export function IntelligenceOptionsScreen() {
  const { path, calendarPath, coreAgenda, mode, setMode, scope, setScope, reset, representatives } = useIntelligence()
  const { user } = useAuth()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const teamView = user?.role === 'admin' || user?.role === 'manager' || path().endsWith('/demo')
  const modules = [
    {
      segment: 'medicos',
      title: 'Perfiles médicos',
      description: 'Consultar contexto por médico',
      icon: Stethoscope,
    },
    {
      segment: 'calendario',
      title: coreAgenda ? 'Agenda' : mode === 'demo' ? 'Calendario de ejemplo' : 'Calendario de visitas',
      description: coreAgenda ? 'Ver todas tus visitas programadas' : 'Ver las visitas que programaste aquí',
      icon: CalendarDays,
    },
    {
      segment: 'aprendizaje',
      title: 'Acerca de las recomendaciones',
      description: 'Cómo se construyen y qué falta',
      icon: BrainCircuit,
    },
    {
      segment: 'resumen',
      title: teamView ? 'Resumen del equipo' : 'Mi actividad',
      description: 'Visitas, reportes, alertas y seguimientos',
      icon: Layers3,
    },
  ]
  return (
    <>
      <header className="intel-mobile-heading">
        <h1>Más contexto</h1>
        <p>Consulta solo lo que necesites.</p>
      </header>
      <div className="intel-mobile-module-list">
        {(user?.role === 'admin' || path().endsWith('/demo')) && (
          <Link to={path().endsWith('/demo') ? '/admin/training/demo' : '/admin/training'}>
            <span className="intel-module-icon"><SlidersHorizontal size={20} /></span>
            <span><strong>Training Builder</strong><small>Diseñar niveles y su evaluación · demostración</small></span>
            <ChevronRight size={18} />
          </Link>
        )}
        {mode === 'demo' && (
          <Link to={path('visita')}>
            <span className="intel-module-icon">
              <CalendarDays size={20} />
            </span>
            <span>
              <strong>Demostrar una visita completa</strong>
              <small>Llegada, llamada, confirmación y seguimiento</small>
            </span>
            <ChevronRight size={18} />
          </Link>
        )}
        {modules.map(({ segment, title, description, icon: Icon }) => (
          <Link key={segment} to={segment === 'calendario' ? calendarPath() : path(segment)}>
            <span className="intel-module-icon">
              <Icon size={20} />
            </span>
            <span>
              <strong>{title}</strong>
              <small>{description}</small>
            </span>
            <ChevronRight size={18} />
          </Link>
        ))}
      </div>
      <MobileAccordion
        title={mode === 'demo' ? 'Opciones de la demostración' : 'Opciones de la vista'}
        icon={SlidersHorizontal}
        open={settingsOpen}
        onToggle={() => setSettingsOpen(!settingsOpen)}
      >
        <p>
          {mode === 'demo'
            ? 'Estos médicos y reportes son ficticios para explorar el flujo completo.'
            : 'El historial y las sugerencias se construyen con los reportes registrados en UNO. La conexión con ESOMED está pendiente.'}
        </p>
        <div className="intel-form">
          <label>
            Datos de la vista
            <select value={mode} onChange={(e) => setMode(e.target.value as 'demo' | 'empty' | 'live')}>
              {!path().includes('/demo') && <option value="live">Reportes de UNO</option>}
              <option value="demo">Datos de ejemplo</option>
              <option value="empty">Sin datos</option>
            </select>
          </label>
          {mode !== 'empty' && (
            <>
              {teamView && (
                <label>
                  Filtrar por visitador
                  <select value={scope} onChange={(e) => setScope(e.target.value)}>
                    <option value="all">Todo el equipo</option>
                    {representatives.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {mode === 'demo' && (
                <button type="button" className="intel-button intel-button--secondary" onClick={reset}>
                  Restablecer ejemplo
                </button>
              )}
            </>
          )}
        </div>
        <p className="intel-small-note">
          {mode === 'demo'
            ? 'Las visitas de ejemplo se guardan solo en esta pestaña.'
            : 'Las visitas que programes se guardan en tu agenda y se envían cuando hay conexión.'}
        </p>
      </MobileAccordion>
    </>
  )
}
