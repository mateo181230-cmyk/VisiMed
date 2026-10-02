import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Phone, Volume2 } from 'lucide-react'
import { useIntelligence } from './IntelligenceProvider'
import { DEMO_DOCTOR_ID, DEMO_VISIT_ID, exampleReport } from './pilotDemo'
import { FIELD_DEFS, displayValue } from '../history/labels'
import { formatTime } from '../../lib/time'
import { IntelButton } from './components'
import { shortDate } from './model'

export function PilotDemoScreen() {
  const { mode, demoSnapshot, updateDemo, path, doctors, reset } = useIntelligence()
  const doctor = doctors.find((d) => d.id === DEMO_DOCTOR_ID)
  const visit = demoSnapshot.visits.find((v) => v.id === DEMO_VISIT_ID)
  const report = demoSnapshot.reports.find((r) => r.visit_id === DEMO_VISIT_ID)
  const [step, setStep] = useState(0)
  const [followup, setFollowup] = useState('2026-10-07')
  const [showCorrection, setShowCorrection] = useState(false)
  const [audio, setAudio] = useState(false)
  const draft = exampleReport(followup)
  const script = [
    `Hola, vi que terminaste tu visita con ${doctor?.name ?? 'el médico'}. Cuéntame rápidamente, ¿cómo te fue?`,
    'Presenté ESOMED para conocer cómo escoge los IBP. Usa pantoprazol por costumbre. Le interesó la formulación y pidió la ficha técnica; no quiere cambiar de inmediato. Me preguntó por disponibilidad.',
    '¿Hubo alguna información nueva que debamos tener en cuenta?',
    'Desde octubre atenderá los miércoles por la mañana. Yo le enviaré la ficha y ella la revisará antes del seguimiento.',
    '¿Cuándo recomiendas volver a visitarla?',
    `El ${shortDate(followup)}.`,
    'Del 1 al 5, ¿qué tan receptivo estuvo?',
    'Cuatro. Escuchó con atención e hizo preguntas. No entregué muestras.',
    '¿Hay algo importante de esta visita que no te haya preguntado?',
    'Coordinar los miércoles por la mañana y confirmar disponibilidad en la farmacia del sector.',
    `${draft.fields.summary!.value} ¿Confirmas este resumen de la visita?`,
  ]
  useEffect(() => {
    if (!audio || visit?.status !== 'in_call' || !window.speechSynthesis) return
    const utterance = new SpeechSynthesisUtterance(script[step]!)
    utterance.lang = 'es-CO'
    window.speechSynthesis.cancel()
    window.speechSynthesis.speak(utterance)
    return () => window.speechSynthesis.cancel()
    // El audio solo sigue el turno visible del guion de demostración.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, audio, visit?.status, followup])

  if (mode !== 'demo') return <p>El recorrido simulado está disponible en la demostración.</p>
  function change(status: string) {
    const base = {
      id: DEMO_VISIT_ID,
      doctor_id: DEMO_DOCTOR_ID,
      representative_id: doctor!.representativeId,
      primary_line_id: 'GASTRU',
      scheduled_at: '2026-09-30T15:00:00Z',
      arrived_at: '2026-09-30T15:00:00Z',
      finished_at: status === 'in_progress' ? null : '2026-09-30T15:08:00Z',
      status,
      arrival_geo_state: 'verificada',
      finish_geo_state: status === 'in_progress' ? null : 'verificada',
    }
    updateDemo({
      ...demoSnapshot,
      visits: [...demoSnapshot.visits.filter((v) => v.id !== DEMO_VISIT_ID), base],
    })
  }
  function save(confirmed: boolean) {
    const r = {
      ...draft,
      status: confirmed ? 'confirmed' : 'ready',
      confirmed_at: confirmed ? '2026-09-30T15:10:00Z' : null,
    }
    updateDemo({
      ...demoSnapshot,
      visits: demoSnapshot.visits.map((v) =>
        v.id === DEMO_VISIT_ID ? { ...v, status: r.status, discussed_line_ids: ['GASTRU'] } : v,
      ),
      reports: [...demoSnapshot.reports.filter((r) => r.visit_id !== DEMO_VISIT_ID), r],
    })
  }
  return (
    <>
      <header className="intel-mobile-heading">
        <h1>Recorrido de una visita</h1>
        <p>Visita, llamada, reporte y seguimiento con datos simulados.</p>
      </header>
      <section className="intel-visit-purpose">
        <strong>{doctor?.name}</strong>
        <p>{doctor?.institution}</p>
        <p>{doctor?.address}</p>
        {visit?.arrived_at && (
          <p>
            Llegada: {formatTime(visit.arrived_at, demoSnapshot.timezone)}
            {visit.finished_at && (
              <>
                {' '}
                · Salida: {formatTime(visit.finished_at, demoSnapshot.timezone)} · Duración:{' '}
                {Math.round((Date.parse(visit.finished_at) - Date.parse(visit.arrived_at)) / 60000)} min
              </>
            )}
          </p>
        )}
        {visit && (
          <p className="intel-small-note">
            Ubicación simulada: llegada {visit.arrival_geo_state ?? 'por registrar'}; salida{' '}
            {visit.finish_geo_state ?? 'por registrar'}.
          </p>
        )}
        <p className="intel-small-note">
          Horarios y GPS de ejemplo. El guion es simulado; las llamadas reales salen al celular con
          ElevenLabs.
        </p>
      </section>
      {!visit && (
        <>
          <p>Antes de llegar: {doctor?.visits[0]?.summary ?? 'Consulta el contexto del médico.'}</p>
          <IntelButton onClick={() => change('in_progress')}>Llegué · 10:00 a. m.</IntelButton>
        </>
      )}
      {visit?.status === 'in_progress' && (
        <>
          <p role="status">Llegada registrada · ubicación verificada (simulada).</p>
          <IntelButton onClick={() => change('finished')}>Terminé · 10:08 a. m.</IntelButton>
        </>
      )}
      {visit?.status === 'finished' && (
        <>
          <p role="status">Visita de 8 minutos. UNO te llama para recoger el reporte.</p>
          <IntelButton
            onClick={() => {
              setStep(0)
              change('in_call')
            }}
          >
            <Phone size={18} /> Contestar llamada simulada
          </IntelButton>
        </>
      )}
      {visit?.status === 'in_call' && (
        <section className="pilot-call">
          <label className="pilot-audio">
            <input type="checkbox" checked={audio} onChange={(e) => setAudio(e.target.checked)} />
            <Volume2 size={16} /> Escuchar guion con la voz del navegador
          </label>
          <ol className="pilot-transcript" aria-label="Conversación simulada">
            {script.slice(0, step + 1).map((text, i) => (
              <li key={i} className={i % 2 ? 'pilot-user' : ''}>
                <strong>{i % 2 ? 'Visitador' : 'UNO'}</strong>
                <p>{text}</p>
              </li>
            ))}
          </ol>
          {step < script.length - 1 ? (
            <IntelButton onClick={() => setStep(step + 1)}>
              {step % 2 ? 'Escuchar a UNO' : 'Responder con el relato de ejemplo'}
            </IntelButton>
          ) : (
            <>
              <p>El agente espera tu respuesta antes de guardar la confirmación.</p>
              <IntelButton onClick={() => save(true)}>Sí, correcto · guardar reporte</IntelButton>
              <IntelButton variant="secondary" onClick={() => setShowCorrection(!showCorrection)}>
                Corregir la fecha de seguimiento
              </IntelButton>
              {showCorrection && (
                <label className="intel-form">
                  Nueva fecha
                  <input
                    aria-label="Nueva fecha de seguimiento"
                    type="date"
                    min="2026-09-30"
                    value={followup}
                    onInput={(e) => {
                      if (e.currentTarget.value) setFollowup(e.currentTarget.value)
                    }}
                    onChange={(e) => {
                      if (e.target.value) setFollowup(e.target.value)
                    }}
                  />
                  <small>El resumen se actualiza antes de confirmarlo.</small>
                </label>
              )}
              <IntelButton variant="quiet" onClick={() => save(false)}>
                Dejar por confirmar en la app
              </IntelButton>
            </>
          )}
        </section>
      )}
      {report && (
        <>
          <p role="status">
            {report.status === 'confirmed'
              ? 'Reporte confirmado y guardado. El historial, los insights y la próxima acción ya incorporan esta visita.'
              : 'Reporte guardado por confirmar. Aún no se usa para insights ni recomendaciones.'}
          </p>
          <div className="intel-visit-purpose">
            <p>{String(report.fields.summary?.value ?? '')}</p>
          </div>
          <dl className="pilot-report">
            {FIELD_DEFS.filter((d) => report.fields[d.key]).map((d) => (
              <div key={d.key}>
                <dt>{d.label}</dt>
                <dd>{displayValue(d.key, report.fields[d.key]!.value) ?? 'No informado'}</dd>
              </div>
            ))}
          </dl>
          {report.status !== 'confirmed' && (
            <IntelButton
              onClick={() => {
                setFollowup(String(report.fields.next_action_date?.value ?? '2026-10-07'))
                const next = {
                  ...report,
                  status: 'confirmed',
                  confirmed_at: '2026-09-30T15:10:00Z',
                }
                updateDemo({
                  ...demoSnapshot,
                  reports: demoSnapshot.reports.map((r) => (r.visit_id === DEMO_VISIT_ID ? next : r)),
                  visits: demoSnapshot.visits.map((v) =>
                    v.id === DEMO_VISIT_ID ? { ...v, status: 'confirmed' } : v,
                  ),
                })
              }}
            >
              Confirmar reporte en la app
            </IntelButton>
          )}
          <div className="intel-mobile-module-list">
            <Link to={path('resumen')}>Ver dashboard, alertas e insights</Link>
            <Link to={path(`medicos/${DEMO_DOCTOR_ID}?linea=GASTRU`)}>
              Ver historial y compromisos del médico
            </Link>
            <Link to={path()}>Ver próxima mejor acción</Link>
          </div>
          <IntelButton
            variant="quiet"
            onClick={() => {
              reset()
              setStep(0)
              setFollowup('2026-10-07')
              setShowCorrection(false)
            }}
          >
            Restablecer ejemplo y repetir recorrido
          </IntelButton>
        </>
      )}
    </>
  )
}
