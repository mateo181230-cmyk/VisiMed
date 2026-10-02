import { CalendarDays, CalendarPlus, Check, Clock3, FileText, MapPin, MessageSquareText } from 'lucide-react'
import { useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useIntelligence } from './IntelligenceProvider'
import { Avatar, EmptyState, IntelButton, LineBadge, Modal, RepresentativeName, ScheduleDialog } from './components'
import { MobileAccordion } from './MobileAccordion'
import { daysBetween, shortDate } from './model'
import { LINE_NAMES, OBSERVATION_LABELS, type LineCode, type Observation } from './types'

export function DoctorProfileScreen() {
  const { doctorId } = useParams()
  const { doctors, mode, state, review, setScope, today } = useIntelligence()
  const [params, setParams] = useSearchParams()
  const [openModule, setOpenModule] = useState<string | null>(params.get('evidencia') ? 'evidence' : null)
  const [planning, setPlanning] = useState(false)
  const [openedObservation, setOpenedObservation] = useState<Observation | null>(null)
  const doctor = doctors.find((d) => d.id === doctorId)
  const rawLine = params.get('linea')
  const line: LineCode =
    rawLine && Object.hasOwn(LINE_NAMES, rawLine) ? (rawLine as LineCode) : (doctor?.profiles[0]?.line ?? 'GASTRU')
  const profile = doctor?.profiles.find((p) => p.line === line)
  const visits = doctor?.visits.filter((v) => v.line === line).sort((a, b) => b.day.localeCompare(a.day)) ?? []
  const observations = doctor?.observations.filter((o) => o.line === line) ?? []
  const report = doctor?.visits.find((v) => v.id === openedObservation?.visitId)
  const toggle = (key: string) => () => setOpenModule(openModule === key ? null : key)

  if (!doctor)
    return (
      <>
        <EmptyState
          title={mode === 'empty' ? 'El perfil aún no está conectado' : 'Este médico no está en el panel seleccionado'}
          description="Vuelve a tus recomendaciones o explora un perfil de ejemplo."
          action={mode === 'empty'}
        />
        {mode === 'demo' && (
          <IntelButton variant="secondary" onClick={() => setScope('all')}>
            Ver todo el equipo
          </IntelButton>
        )}
      </>
    )
  return (
    <>
      <header className="intel-mobile-heading intel-visit-detail-heading">
        <p className="intel-mini-label">PERFIL MÉDICO</p>
        <div className="intel-mobile-identity">
          <Avatar doctor={doctor} />
          <div>
            <h1>{doctor.name}</h1>
            <p>{doctor.institution}</p>
          </div>
        </div>
      </header>
      <div className="intel-mobile-line-select" aria-label="Línea del perfil">
        {(Object.keys(LINE_NAMES) as LineCode[]).map((code) => (
          <button
            type="button"
            key={code}
            aria-pressed={code === line}
            onClick={() => {
              setParams({ linea: code })
              setOpenModule(null)
            }}
          >
            {LINE_NAMES[code]}
          </button>
        ))}
      </div>
      {!profile ? (
        <section className="intel-mobile-no-context">
          <h2>Aún no hay contexto de {LINE_NAMES[line]}</h2>
          <p>Hace falta una primera conversación sobre esta línea.</p>
          <IntelButton onClick={() => setPlanning(true)}>
            <CalendarPlus size={18} /> Planear visita
          </IntelButton>
        </section>
      ) : (
        <>
          <section className="intel-visit-purpose">
            <span>Próximo paso</span>
            <p>{profile.nextStep}</p>
          </section>
          <div className="intel-detail-actions intel-detail-actions--before-modules">
            <IntelButton onClick={() => setPlanning(true)}>
              <CalendarPlus size={18} /> Planear visita
            </IntelButton>
          </div>
          <MobileAccordion
            title="Contexto de esta línea"
            icon={MessageSquareText}
            open={openModule === 'context'}
            onToggle={toggle('context')}
          >
            <p>{profile.summary}</p>
            <p className="intel-small-note">
              {mode === 'demo' ? 'Síntesis de ejemplo' : 'Síntesis del último reporte confirmado'} basada en reportes
              del equipo. Consulta la evidencia antes de decidir.
            </p>
          </MobileAccordion>
          <MobileAccordion
            title="Observaciones y evidencia"
            icon={FileText}
            open={openModule === 'evidence'}
            onToggle={toggle('evidence')}
          >
            {observations.map((o) => (
              <article key={o.id} className="intel-mobile-observation">
                <div className="intel-observation-label">
                  <span>{OBSERVATION_LABELS[o.kind]}</span>
                  <span className={o.confirmed ? 'intel-evidence-confirmed' : 'intel-evidence-pending'}>
                    {o.confirmed
                      ? 'Confirmado por visitador'
                      : state.reviewed.includes(o.id)
                        ? 'Revisada · falta confirmación'
                        : 'Por confirmar'}
                  </span>
                </div>
                <p>{o.text}</p>
                <small>
                  <RepresentativeName id={o.representativeId} /> · {shortDate(o.day)}
                </small>
                <button type="button" onClick={() => setOpenedObservation(o)}>
                  <FileText size={15} /> Ver reporte
                </button>
              </article>
            ))}
            {!observations.length && <p>Sin observaciones para esta línea.</p>}
            <p className="intel-small-note">
              Confirmar un reporte no convierte una opinión en un hecho sobre el médico.
            </p>
          </MobileAccordion>
          <MobileAccordion
            title="Historial de conversaciones"
            icon={Clock3}
            open={openModule === 'history'}
            onToggle={toggle('history')}
          >
            <p className="intel-detail-highlight">
              {visits[0] ? `Última visita: hace ${daysBetween(visits[0].day, today)} días` : 'Sin visitas registradas'}
            </p>
            <ol className="intel-mobile-history">
              {visits.map((v) => (
                <li key={v.id}>
                  <strong>{shortDate(v.day)}</strong>
                  <p>{v.summary}</p>
                  <small>
                    <RepresentativeName id={v.representativeId} /> ·{' '}
                    {v.confirmed ? 'Reporte confirmado' : 'Reporte por confirmar'}
                  </small>
                </li>
              ))}
            </ol>
          </MobileAccordion>
          <MobileAccordion
            title="Para coordinar la visita"
            icon={MapPin}
            open={openModule === 'contact'}
            onToggle={toggle('contact')}
          >
            <dl className="intel-mobile-facts">
              <div>
                <dt>Consultorio</dt>
                <dd>
                  {doctor.institution}
                  <small>{doctor.address}</small>
                </dd>
              </div>
              <div>
                <dt>Franja reportada</dt>
                <dd>
                  {doctor.availability}
                  <small>Confirma con el consultorio.</small>
                </dd>
              </div>
              <div>
                <dt>Visitador</dt>
                <dd>
                  <RepresentativeName id={doctor.representativeId} />
                </dd>
              </div>
              <div>
                <dt>Especialidad</dt>
                <dd>{doctor.specialty}</dd>
              </div>
            </dl>
          </MobileAccordion>
        </>
      )}
      <ScheduleDialog open={planning} onClose={() => setPlanning(false)} doctorId={doctor.id} initialLine={line} />
      <Modal
        open={!!openedObservation}
        onClose={() => setOpenedObservation(null)}
        title="Reporte que origina la observación"
      >
        {openedObservation && (
          <>
            <div className="intel-report-meta">
              <LineBadge line={openedObservation.line} />
              <span>
                <CalendarDays size={14} />
                {shortDate(openedObservation.day)}
              </span>
            </div>
            <h3 className="intel-report-doctor">{doctor.name}</h3>
            <p className="intel-small-note">
              <RepresentativeName id={openedObservation.representativeId} />
            </p>
            <div className="intel-report-quote">
              <span>RESUMEN DEL REPORTE DE EJEMPLO</span>
              <p>{report?.summary ?? openedObservation.text}</p>
            </div>
            <div className="intel-report-quote intel-report-quote--observation">
              <span>OBSERVACIÓN EXTRAÍDA</span>
              <p>{openedObservation.text}</p>
            </div>
            <p className="intel-small-note">
              {openedObservation.confirmed
                ? 'El visitador confirmó este reporte en el ejemplo.'
                : 'Revisarlo aquí no lo confirma. Falta validarlo con quien realizó la visita.'}
            </p>
            <div className="intel-dialog-actions">
              <IntelButton variant="secondary" onClick={() => setOpenedObservation(null)}>
                Cerrar
              </IntelButton>
              {!openedObservation.confirmed && (
                <IntelButton
                  disabled={state.reviewed.includes(openedObservation.id)}
                  onClick={() => review(openedObservation.id)}
                >
                  <Check size={17} />
                  {state.reviewed.includes(openedObservation.id) ? 'Revisada' : 'Marcar como revisada'}
                </IntelButton>
              )}
            </div>
          </>
        )}
      </Modal>
    </>
  )
}
