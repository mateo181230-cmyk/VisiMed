import { BadgeCheck, Clock3, Maximize2, Mic, PhoneOff, Play, X } from 'lucide-react'
import { useState, type CSSProperties } from 'react'
import { agents, backgrounds, type TrainingLevel } from './model'

/** El entorno de la presentación es independiente de la futura estrategia de video de Tavus. */
export function AgentStage({ level, compact = false }: { level: TrainingLevel; compact?: boolean }) {
  const agent = agents.find(a => a.id === level.agentId) ?? agents[0]!
  const environment = backgrounds.find(b => b.id === level.background) ?? backgrounds[0]!
  const style: CSSProperties = {
    '--stage-color': environment.color,
    '--level-accent': level.accent,
    ...(level.backgroundImage ? { backgroundImage: 'url(' + JSON.stringify(level.backgroundImage) + ')' } : {}),
  } as CSSProperties
  return (
    <div className={'tb-stage ' + (compact ? 'tb-stage--compact' : '') + ' tb-stage--' + level.layout} style={style}>
      <div className="tb-stage-window" aria-hidden />
      <div className="tb-stage-plant" aria-hidden><i /><i /><i /></div>
      <span className="tb-stage-label"><span /> {environment.name}</span>
      <div className="tb-stage-portrait">
        <img src={agent.photo} alt={level.characterName} />
      </div>
      <div className="tb-stage-caption">
        <span className="tb-stage-online" />
        <div><strong>{level.characterName}</strong><small>{level.specialty} · Agente virtual</small></div>
        <Maximize2 size={15} aria-hidden />
      </div>
      {level.showBrand && <span className="tb-stage-brand">NOVAMED<span> / training</span></span>}
    </div>
  )
}

export function ScenarioPreview({ level, onClose }: { level: TrainingLevel; onClose: () => void }) {
  const [phase, setPhase] = useState<'intro' | 'conversation' | 'result'>('intro')
  const [step, setStep] = useState(0)
  const examples = [
    { rep: 'Doctor, ¿qué tiene en cuenta al elegir el tratamiento para sus pacientes?', doctor: 'Principalmente la respuesta clínica. Hoy uso otro producto y no veo una diferencia clara.' },
    { rep: 'Entiendo que necesita una diferencia respaldada por evidencia. ¿Puedo mostrarle el perfil de paciente y el soporte clínico?', doctor: 'Sí, pero sea concreto. Me interesa saber en qué paciente haría una diferencia.' },
    { rep: 'Podemos revisar la ficha técnica y retomar la conversación con esa evidencia en mi próxima visita.', doctor: 'Está bien. Revisemos esa información en la próxima visita.' },
  ]
  const active = level.objectives.filter(o => o.active)
  const scores = [75, 88, 78, 90]
  const total = Math.round(active.reduce((sum, o, i) => sum + o.weight * (scores[i % scores.length] ?? 80) / 100, 0))
  const passed = total >= level.passingScore
  return (
    <div className="tb-modal-backdrop" onClick={onClose}>
      <section className="tb-simulation" role="dialog" aria-modal aria-labelledby="simulation-title" onClick={e => e.stopPropagation()}>
        <header>
          <div><span className="tb-eyebrow">VISTA DEL ESTUDIANTE</span><h2 id="simulation-title">{phase === 'result' ? 'Resultado de ejemplo' : level.name}</h2></div>
          <button className="tb-icon-button" onClick={onClose} aria-label="Cerrar prueba"><X size={20} /></button>
        </header>
        <p className="tb-demo-note">Recorrido simulado. No usa el micrófono, no conecta con Tavus y no genera un resultado real.</p>
        {phase !== 'result' ? <>
          <div className="tb-simulation-stage">
            <AgentStage level={level} />
            {phase === 'conversation' && <span className="tb-simulation-timer"><Clock3 size={14} /> 00:{String(15 + step * 20).padStart(2, '0')}</span>}
          </div>
          {phase === 'intro' ? (
            <div className="tb-simulation-body">
              <span className="tb-chip">{level.difficulty} · {level.minutes} minutos</span>
              <h3>Tu objetivo</h3><p>{level.learnerGoal || 'Explorar la necesidad, responder una objeción y definir un próximo paso.'}</p>
              <button className="tb-button tb-button--primary" onClick={() => setPhase('conversation')}><Play size={17} /> Comenzar ejemplo</button>
            </div>
          ) : (
            <div className="tb-simulation-body">
              <div className="tb-dialogue"><span>{level.characterName}</span><p>“{step === 0 ? level.greeting : examples[(step - 1) % examples.length]!.doctor}”</p></div>
              <div className="tb-simulation-controls">
                <button className="tb-button tb-button--soft" onClick={() => setStep(s => s + 1)}><Mic size={17} /> Avanzar conversación de ejemplo</button>
                <button className="tb-button tb-button--danger" onClick={() => setPhase('result')}><PhoneOff size={17} /> Finalizar</button>
              </div>
              {step > 0 && <p className="tb-example-answer"><strong>Visitador:</strong> {examples[(step - 1) % examples.length]!.rep}</p>}
            </div>
          )}
        </> : (
          <div className="tb-simulation-body tb-demo-result">
            <div className="tb-result-score"><strong>{total}<small>/100</small></strong><span><BadgeCheck size={20} /> {passed ? 'Nivel superado' : 'Continúa practicando'}</span></div>
            <p>{passed ? level.passedMessage : level.failedMessage}</p>
            <div className="tb-result-dimensions">{active.map((o, i) => <div key={o.id}><span>{o.name}<small>Peso {o.weight} %{o.required ? ' · Obligatorio' : ''}</small></span><strong>{scores[i % scores.length]}/100</strong><div><i style={{ width: (scores[i % scores.length] ?? 80) + '%' }} /></div></div>)}</div>
            <div className="tb-result-feedback"><div><h3>Fortaleza</h3><p>Conectaste la propuesta con el criterio clínico del médico.</p></div><div><h3>Qué mejorar</h3><p>Confirma que la objeción quedó resuelta antes de pasar al cierre.</p></div></div>
            <p className="tb-recommendation">{level.recommendation}</p>
            <button className="tb-button tb-button--primary" onClick={onClose}>Volver al editor</button>
          </div>
        )}
      </section>
    </div>
  )
}
