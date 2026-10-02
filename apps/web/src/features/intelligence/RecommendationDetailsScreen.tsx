import {
  CalendarDays,
  CalendarPlus,
  Check,
  Clock3,
  FileText,
  MapPin,
  MessageSquareText,
  Package,
  Sparkles,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { format12 } from '../../lib/time'
import { Avatar, EmptyState, IntelButton, Modal, RepresentativeName } from './components'
import { useIntelligence } from './IntelligenceProvider'
import { MobileAccordion } from './MobileAccordion'
import { ProgramRecommendationDialog } from './ProgramRecommendationDialog'
import { daysBetween, shortDate } from './model'
import { LINE_NAMES } from './types'

export function RecommendationDetailsScreen() {
  const { recommendationId } = useParams()
  const { path, calendarPath, doctors, recommendations, state, dismiss, visits, today, mode } = useIntelligence()
  const [openModule, setOpenModule] = useState<string | null>(null)
  const [planning, setPlanning] = useState(false)
  const [skipping, setSkipping] = useState(false)
  const [skipReason, setSkipReason] = useState('')
  const r = recommendations.find((r) => r.id === recommendationId)
  const doctor = doctors.find((d) => d.id === r?.doctorId)
  if (!r || !doctor)
    return (
      <EmptyState
        title="Esta recomendación no está disponible"
        description="Vuelve a la lista para consultar las visitas de tu panel."
        action={false}
      />
    )
  const history = doctor.visits.filter((v) => v.line === r.line).sort((a, b) => b.day.localeCompare(a.day))
  const last = history[0]
  const observations = doctor.observations.filter((o) => o.line === r.line)
  const decision = state.decisions[r.id]
  const planned = visits.find((v) => v.recommendationId === r.id)
  const toggle = (key: string) => () => setOpenModule(openModule === key ? null : key)
  return (
    <>
      <header className="intel-mobile-heading intel-visit-detail-heading">
        <p className="intel-mini-label">DETALLES DE LA VISITA</p>
        <div className="intel-mobile-identity">
          <Avatar doctor={doctor} />
          <div>
            <h1>{doctor.name}</h1>
            <p>{doctor.institution}</p>
          </div>
        </div>
      </header>
      <div className="intel-detail-slot">
        <CalendarDays size={18} />
        <span>
          {shortDate(planned?.day ?? r.day)} · {format12(planned?.time ?? r.time)}
        </span>
        <small>{planned ? 'Programada' : 'Sugerida'}</small>
      </div>
      <section className="intel-visit-purpose">
        <span>Qué hacer en esta visita</span>
        <p>{r.description}</p>
      </section>
      <div className="intel-detail-actions intel-detail-actions--before-modules">
        {decision?.status === 'accepted' ? (
          <Link to={calendarPath(planned?.day ?? r.day)} className="intel-button intel-button--primary">
            <Check size={18} /> Ver visita programada
          </Link>
        ) : decision?.status === 'dismissed' ? (
          <p className="intel-small-note">Descartada{decision.reason ? ` · ${decision.reason}` : ''}</p>
        ) : (
          <IntelButton onClick={() => setPlanning(true)}>
            <CalendarPlus size={18} /> Programar visita
          </IntelButton>
        )}
      </div>
      <div className="intel-detail-modules">
        <MobileAccordion
          title="Por qué esta visita"
          icon={Sparkles}
          open={openModule === 'why'}
          onToggle={toggle('why')}
        >
          <ul className="intel-mobile-evidence">
            {r.reasons.map((reason) => {
              const o = observations.find((o) => o.id === reason.observationId)
              return (
                <li key={reason.observationId}>
                  <p>{reason.text}</p>
                  {o && (
                    <small>
                      <RepresentativeName id={o.representativeId} /> · {shortDate(o.day)} · Reporte confirmado
                    </small>
                  )}
                </li>
              )
            })}
          </ul>
          <p className="intel-small-note">
            Son percepciones reportadas por el visitador.{' '}
            {mode === 'demo'
              ? 'Este ejemplo ilustra el seguimiento.'
              : 'El piloto prioriza seguimientos por fecha y contexto desactualizado mediante reglas.'}
          </p>
          <Link
            to={path(`medicos/${doctor.id}?linea=${r.line}&evidencia=${r.reasons[0]?.observationId}`)}
            className="intel-text-link"
          >
            <FileText size={15} /> Ver reportes del perfil
          </Link>
        </MobileAccordion>
        <MobileAccordion
          title="Última visita e historial"
          icon={MessageSquareText}
          open={openModule === 'history'}
          onToggle={toggle('history')}
        >
          {last ? (
            <p className="intel-detail-highlight">
              Última visita: {shortDate(last.day)} · Hace {daysBetween(last.day, today)} días
            </p>
          ) : (
            <p>Sin visitas registradas para esta línea.</p>
          )}
          <ol className="intel-mobile-history">
            {history.map((v) => (
              <li key={v.id}>
                <strong>{shortDate(v.day)}</strong>
                <p>{v.summary}</p>
                <small>
                  <RepresentativeName id={v.representativeId} /> ·{' '}
                  {v.confirmed ? 'Reporte confirmado' : 'Por confirmar'}
                </small>
              </li>
            ))}
          </ol>
        </MobileAccordion>
        <MobileAccordion
          title="Productos e intereses"
          icon={Package}
          open={openModule === 'products'}
          onToggle={toggle('products')}
        >
          <p className="intel-detail-highlight">Línea: {LINE_NAMES[r.line]}</p>
          <ul className="intel-mobile-evidence">
            {observations
              .filter((o) => o.kind === 'interest' || o.kind === 'commitment')
              .map((o) => (
                <li key={o.id}>
                  <p>{o.text}</p>
                  <small>
                    {shortDate(o.day)} · {o.confirmed ? 'Confirmado por visitador' : 'Por confirmar'}
                  </small>
                </li>
              ))}
          </ul>
        </MobileAccordion>
        <MobileAccordion
          title="Frecuencia y prioridad"
          icon={Clock3}
          open={openModule === 'frequency'}
          onToggle={toggle('frequency')}
        >
          <dl className="intel-mobile-facts">
            <div>
              <dt>Frecuencia recomendada</dt>
              <dd>Aún sin una frecuencia validada.</dd>
            </div>
            <div>
              <dt>Prioridad</dt>
              <dd>
                {r.type === 'followup' ? 'Seguimiento de un acuerdo pendiente.' : 'Explorar una nueva conversación.'}
              </dd>
            </div>
            <div>
              <dt>Orden de la lista</dt>
              <dd>
                {mode === 'demo' ? 'Orden ilustrativo del ejemplo.' : 'Fecha de seguimiento y contexto por actualizar.'}
              </dd>
            </div>
          </dl>
        </MobileAccordion>
        <MobileAccordion
          title="Territorio y disponibilidad"
          icon={MapPin}
          open={openModule === 'territory'}
          onToggle={toggle('territory')}
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
              <dt>Zona</dt>
              <dd>{doctor.zone}</dd>
            </div>
            <div>
              <dt>Franja reportada</dt>
              <dd>
                {doctor.availability}
                <small>
                  {r.availabilityConfirmed
                    ? 'Reportada por el visitador. Confirma con el consultorio.'
                    : 'Disponibilidad por confirmar.'}
                </small>
              </dd>
            </div>
            <div>
              <dt>Close-Up</dt>
              <dd>Sin datos conectados.</dd>
            </div>
          </dl>
        </MobileAccordion>
      </div>
      {!decision && (
        <button type="button" className="intel-skip-suggestion" onClick={() => setSkipping(true)}>
          No es el momento
        </button>
      )}
      <ProgramRecommendationDialog recommendation={planning ? r : null} onClose={() => setPlanning(false)} />
      <Modal open={skipping} onClose={() => setSkipping(false)} title="Descartar sugerencia">
        <p className="intel-modal-copy">Puedes indicar un motivo. Es opcional.</p>
        <div className="intel-reason-options">
          {['No es posible', 'El médico pidió otra cosa', 'Ya lo visité'].map((reason) => (
            <button
              type="button"
              key={reason}
              aria-pressed={skipReason === reason}
              onClick={() => setSkipReason(skipReason === reason ? '' : reason)}
            >
              {reason}
            </button>
          ))}
        </div>
        <div className="intel-dialog-actions">
          <IntelButton variant="secondary" onClick={() => setSkipping(false)}>
            Volver
          </IntelButton>
          <IntelButton
            onClick={() => {
              dismiss(r.id, skipReason || undefined)
              setSkipping(false)
            }}
          >
            Descartar
          </IntelButton>
        </div>
      </Modal>
    </>
  )
}
