import { AlertTriangle, CalendarDays, FileText, Lightbulb, Stethoscope } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useIntelligence } from './IntelligenceProvider'
import { EmptyState } from './components'
import { MobileAccordion } from './MobileAccordion'
import { shortDate } from './model'
import { useAuth } from '../auth/AuthProvider'
import { AdminDashboard } from './AdminDashboard'

export function IntelligenceOverview() {
  const { mode, doctors, path, calendarPath, analysis, representatives, scope, setScope } = useIntelligence()
  const [openModule, setOpenModule] = useState<string | null>(null)
  const { user } = useAuth()
  if (user?.role === 'admin' && !path().includes('/demo')) return <AdminDashboard />
  const toggle = (key: string) => () => setOpenModule(openModule === key ? null : key)
  const m = analysis?.metrics
  const signals = (items: { label: string; count: number }[]) =>
    items.length ? (
      <ul className="intel-mobile-evidence">
        {items.map((s) => (
          <li key={s.label}>
            <p>{s.label}</p>
            <small>
              {s.count} {s.count === 1 ? 'visita' : 'visitas'}
            </small>
          </li>
        ))}
      </ul>
    ) : (
      <p>Sin menciones confirmadas en este período.</p>
    )
  return (
    <>
      <header className="intel-mobile-heading">
        <h1>{representatives.length === 1 && mode === 'live' ? 'Mi actividad' : 'Resumen del equipo'}</h1>
        <p>Actividad de los últimos 30 días y contexto para continuar las visitas.</p>
      </header>
      {mode === 'empty' || !analysis || !m ? (
        <EmptyState
          title="El aprendizaje comienza con la primera visita"
          description="Registra y confirma una visita para alimentar el resumen."
        />
      ) : (
        <>
          {representatives.length > 1 && (
            <label className="intel-form">
              Visitador
              <select aria-label="Visitador del dashboard" value={scope} onChange={(e) => setScope(e.target.value)}>
                <option value="all">Todo el equipo</option>
                {representatives.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <dl className="pilot-metrics">
            <div>
              <dt>Visitas realizadas</dt>
              <dd>{m.completed}</dd>
            </div>
            <div>
              <dt>Médicos visitados</dt>
              <dd>{m.doctorsVisited}</dd>
            </div>
            <div>
              <dt>Duración promedio</dt>
              <dd>{m.averageMinutes === null ? 'Sin dato' : `${m.averageMinutes.toFixed(1)} min`}</dd>
            </div>
            <div>
              <dt>Ubicación validada</dt>
              <dd>
                {m.verified} / {m.completed}
              </dd>
            </div>
            <div>
              <dt>Reportes confirmados</dt>
              <dd>{m.confirmed}</dd>
            </div>
            <div>
              <dt>Por confirmar</dt>
              <dd>{m.toConfirm}</dd>
            </div>
          </dl>
          <p className="intel-small-note">
            {mode === 'demo' ? 'Datos ficticios del piloto.' : 'Datos registrados en UNO.'} La integración con ESOMED
            está pendiente. Duración calculada entre llegada y salida; promedios excluyen duraciones negativas o
            superiores a 3 horas.
          </p>
          <MobileAccordion
            title="Cumplimiento por visitador"
            icon={Stethoscope}
            open={openModule === 'reps'}
            onToggle={toggle('reps')}
          >
            <div className="pilot-table">
              <table>
                <thead>
                  <tr>
                    <th>Visitador</th>
                    <th>Realizadas / agenda vencida</th>
                    <th>Cumplimiento</th>
                  </tr>
                </thead>
                <tbody>
                  {m.byRep.map((r) => (
                    <tr key={r.id}>
                      <td>{r.name}</td>
                      <td>
                        {r.completed} / {r.planned}
                      </td>
                      <td>{r.compliance === null ? 'Sin agenda' : `${r.compliance}%`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="intel-small-note">
              Se compara la agenda cuya hora ya pasó con las visitas terminadas de esa agenda. Una visita cancelada
              sigue contando en lo planeado.
            </p>
          </MobileAccordion>
          <MobileAccordion
            title="Actividad diaria y productos presentados"
            icon={CalendarDays}
            open={openModule === 'activity'}
            onToggle={toggle('activity')}
          >
            <ul className="intel-mobile-evidence">
              {m.daily.map((d) => (
                <li key={d.day}>
                  <strong>{shortDate(d.day)}</strong>
                  <p>{d.completed} visitas realizadas</p>
                </li>
              ))}
            </ul>
            <h3>Productos mencionados en reportes confirmados</h3>
            {signals(analysis.insights.products)}
            <Link className="intel-text-link" to={calendarPath()}>
              Ver próximas visitas
            </Link>
          </MobileAccordion>
          <MobileAccordion
            title={`Alertas por revisar · ${analysis.alerts.length}`}
            icon={AlertTriangle}
            open={openModule === 'alerts'}
            onToggle={toggle('alerts')}
          >
            {analysis.alerts.length ? (
              <ul className="intel-mobile-evidence">
                {analysis.alerts.map((a) => (
                  <li key={a.id}>
                    <strong>{a.title}</strong>
                    <p>{doctors.find((d) => d.id === a.doctorId)?.name}</p>
                    <p>{a.detail}</p>
                    <Link className="intel-text-link" to={path(`medicos/${a.doctorId}`)}>
                      Revisar contexto
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No se detectaron señales con las reglas del piloto.</p>
            )}
            <p className="intel-small-note">
              Reglas iniciales: menos de 3 minutos, más de 3 horas, 3 visitas de la misma línea en 7 días, más de 90
              días sin contacto, ubicación sin validar o reporte incompleto. Cada alerta requiere revisar el contexto.
            </p>
          </MobileAccordion>
          <MobileAccordion
            title="Insights de visitas confirmadas"
            icon={Lightbulb}
            open={openModule === 'insights'}
            onToggle={toggle('insights')}
          >
            <h3>Objeciones y preguntas que se repiten</h3>
            <p className="intel-small-note">
              Se agrupan por temas mencionados; consulta el texto original en el historial.
            </p>
            {signals(analysis.insights.objections)}
            <h3>Interés por producto</h3>
            <ul className="intel-mobile-evidence">
              {analysis.insights.productInterest.map((p) => (
                <li key={p.label}>
                  <strong>{p.label}</strong>
                  <p>
                    {p.interested} de {p.reports} visitas con interés reportado
                  </p>
                </li>
              ))}
            </ul>
            <h3>Qué les interesó</h3>
            {signals(analysis.insights.interests)}
            <h3>Competidores mencionados</h3>
            {signals(analysis.insights.competitors)}
            <h3>Médicos con mayor receptividad reportada</h3>
            <ul className="intel-mobile-evidence">
              {analysis.insights.receptive.map((r) => (
                <li key={r.doctorId}>
                  <Link className="intel-text-link" to={path(`medicos/${r.doctorId}`)}>
                    {r.name}
                  </Link>
                  <p>
                    {r.score.toFixed(1)} / 5 · {r.reports} reportes
                  </p>
                </li>
              ))}
            </ul>
            <h3>Actividad por territorio</h3>
            <ul className="intel-mobile-evidence">
              {analysis.insights.territories.map((t) => (
                <li key={t.zone}>
                  <strong>{t.zone}</strong>
                  <p>{t.reports} reportes confirmados</p>
                  {t.signals.map((s, i) => (
                    <p key={i}>{s}</p>
                  ))}
                </li>
              ))}
            </ul>
            <p className="intel-small-note">
              Se agregan solo datos confirmados y sin baja confianza. Las puntuaciones son percepciones del visitador;
              los conteos describen visitas, no ventas ni eficacia clínica.
            </p>
          </MobileAccordion>
          <MobileAccordion
            title={`Historial del médico · ${doctors.length} perfiles`}
            icon={FileText}
            open={openModule === 'doctors'}
            onToggle={toggle('doctors')}
          >
            <p>
              Consulta lo conversado, información nueva y compromisos reportados antes de la próxima visita. El
              cumplimiento de un compromiso debe verificarse; una nueva visita no lo prueba.
            </p>
            <Link className="intel-text-link" to={path('medicos')}>
              Ver perfiles médicos
            </Link>
            <p className="intel-small-note">Historial consultado: hasta 365 días en UNO.</p>
          </MobileAccordion>
        </>
      )}
    </>
  )
}
