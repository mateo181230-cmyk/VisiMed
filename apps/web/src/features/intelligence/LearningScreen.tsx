import { BrainCircuit, Database, FileText, LockKeyhole, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useIntelligence } from './IntelligenceProvider'
import { MobileAccordion } from './MobileAccordion'

export function LearningScreen() {
  const { mode, doctors, path } = useIntelligence()
  const [openModule, setOpenModule] = useState<string | null>(null)
  const reports = doctors.flatMap((d) => d.visits)
  const confirmed = reports.filter((v) => v.confirmed).length
  const toggle = (key: string) => () => setOpenModule(openModule === key ? null : key)
  return (
    <>
      <header className="intel-mobile-heading">
        <h1>Cómo funciona</h1>
        <p>El contexto detrás de la próxima visita.</p>
      </header>
      <section className="intel-learning-status-mobile">
        <strong>
          <BrainCircuit size={21} />
          Machine learning · Aún sin entrenar
        </strong>
        <p>
          {mode === 'live'
            ? 'El piloto usa reglas de seguimiento y reportes confirmados de UNO. Falta validar su utilidad con visitas reales.'
            : 'La demostración usa datos ficticios y reglas de seguimiento.'}
        </p>
      </section>
      <MobileAccordion
        title="De la visita a la recomendación"
        icon={Sparkles}
        open={openModule === 'process'}
        onToggle={toggle('process')}
      >
        <ol className="intel-mobile-history">
          <li>
            <strong>1. Registrar</strong>
            <p>El visitador resume lo que ocurrió y confirma su reporte.</p>
          </li>
          <li>
            <strong>2. Reunir contexto</strong>
            <p>Los acuerdos, intereses y solicitudes se organizan por médico y línea de producto.</p>
          </li>
          <li>
            <strong>3. Proponer una visita</strong>
            <p>El sistema sugiere a quién visitar, cuándo y con qué propósito. El visitador decide.</p>
          </li>
          <li>
            <strong>4. Aprender y validar</strong>
            <p>Con datos reales se podrá entrenar un modelo y comprobar si mejora la planificación.</p>
          </li>
        </ol>
      </MobileAccordion>
      <MobileAccordion
        title="Qué información está disponible"
        icon={Database}
        open={openModule === 'data'}
        onToggle={toggle('data')}
      >
        {mode === 'demo' ? (
          <>
            <p>
              {doctors.length} perfiles médicos y {reports.length} reportes de ejemplo; {confirmed} están confirmados
              por el visitador ficticio.
            </p>
            <p className="intel-small-note">Conteos ficticios. No indican la calidad de un modelo real.</p>
          </>
        ) : (
          <p>
            {mode === 'live'
              ? `${doctors.length} perfiles y ${reports.length} reportes registrados en UNO; ${confirmed} confirmados.`
              : 'Aún no hay datos cargados.'}
          </p>
        )}
        <p>
          La conexión a médicos, visitadores, rutas, instituciones y reportes históricos de ESOMED requiere acceso a su
          sistema.
        </p>
      </MobileAccordion>
      <MobileAccordion
        title="De dónde sale cada motivo"
        icon={FileText}
        open={openModule === 'evidence'}
        onToggle={toggle('evidence')}
      >
        <p>
          Cada motivo debe conservar su reporte de origen, fecha, línea y visitador. Las correcciones del visitador
          tienen prioridad.
        </p>
        <p>
          Las sugerencias del ejemplo se basan en acuerdos pendientes, materiales solicitados y contactos por conocer.
        </p>
        <Link to={path('medicos')} className="intel-text-link">
          Consultar perfiles médicos
        </Link>
      </MobileAccordion>
      <MobileAccordion
        title="Qué datos forman parte del perfil"
        icon={LockKeyhole}
        open={openModule === 'boundaries'}
        onToggle={toggle('boundaries')}
      >
        <p>Observaciones de visitas, próximos pasos, disponibilidad y resultados comerciales con su fuente.</p>
        <p>
          Se excluyen datos de pacientes y etiquetas sobre personalidad. Antes del uso real se debe definir el
          tratamiento de datos y la finalidad del aprendizaje.
        </p>
      </MobileAccordion>
    </>
  )
}
