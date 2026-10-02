import {
  ArrowDown, ArrowLeft, ArrowRight, ArrowUp, BookOpen, Check, CheckCircle2, ChevronDown,
  ChevronRight, Clock3, Copy, Eye, FileText, GraduationCap, GripVertical, ImagePlus,
  LayoutGrid, ListChecks, LoaderCircle, MessageSquare, MoreHorizontal, Pause, Play,
  Plus, RotateCcw, Save, Search, Settings2, ShieldCheck, SlidersHorizontal, Sparkles,
  Target, Trash2, Users, Video, WandSparkles, X,
} from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { AgentStage, ScenarioPreview } from './AgentStage'
import {
  STORAGE_KEY, agents, backgrounds, compilePrompt, initialPrograms, knowledgeMaterials, newLevel,
  readPrograms, validation, type EditorTab, type Objective, type TrainingLevel, type TrainingProgram,
} from './model'
import './training-builder.css'

const tabs: { id: EditorTab; label: string; icon: typeof Settings2 }[] = [
  { id: 'general', label: 'General', icon: Settings2 },
  { id: 'agent', label: 'Agente', icon: Users },
  { id: 'scenario', label: 'Escenario', icon: MessageSquare },
  { id: 'objectives', label: 'Objetivos', icon: Target },
  { id: 'evaluation', label: 'Evaluación', icon: ListChecks },
  { id: 'environment', label: 'Entorno', icon: ImagePlus },
  { id: 'feedback', label: 'Feedback', icon: BookOpen },
  { id: 'advanced', label: 'Configuración avanzada', icon: SlidersHorizontal },
]
const statusNames = { active: 'Activo', draft: 'Borrador', inactive: 'Inactivo' }

function Input({ label, value, onChange, hint, type = 'text', min, max, readOnly }: {
  label: string; value: string | number; onChange: (value: string) => void; hint?: string; type?: string; min?: number; max?: number; readOnly?: boolean
}) {
  return <label className="tb-field"><span>{label}</span><input type={type} value={value} min={min} max={max} readOnly={readOnly} onChange={e => onChange(e.target.value)} />{hint && <small>{hint}</small>}</label>
}
function Textarea({ label, value, onChange, hint, rows = 3 }: { label: string; value: string; onChange: (value: string) => void; hint?: string; rows?: number }) {
  return <label className="tb-field"><span>{label}</span><textarea rows={rows} value={value} onChange={e => onChange(e.target.value)} />{hint && <small>{hint}</small>}</label>
}
function Select({ label, value, onChange, children }: { label: string; value: string; onChange: (value: string) => void; children: ReactNode }) {
  return <label className="tb-field"><span>{label}</span><select value={value} onChange={e => onChange(e.target.value)}>{children}</select></label>
}
function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: () => void; label: string; hint?: string }) {
  return <label className="tb-toggle-row"><span><strong>{label}</strong>{hint && <small>{hint}</small>}</span><input type="checkbox" checked={checked} onChange={onChange} /><span className="tb-switch" aria-hidden /></label>
}
function SectionHeading({ title, description }: { title: string; description: string }) {
  return <div className="tb-section-heading"><h2>{title}</h2><p>{description}</p></div>
}
function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const previous = document.activeElement
    ref.current?.querySelector<HTMLButtonElement>('button')?.focus()
    function key(e: KeyboardEvent) {
      if (e.key === 'Escape') closeRef.current()
      if (e.key === 'Tab') {
        const elements = ref.current?.querySelectorAll<HTMLElement>('button, input, select, textarea, [tabindex="0"]')
        const first = elements?.[0], last = elements?.[elements.length - 1]
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() }
        if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
      }
    }
    window.addEventListener('keydown', key)
    return () => { window.removeEventListener('keydown', key); if (previous instanceof HTMLElement) previous.focus() }
  }, [])
  return <div className="tb-modal-backdrop" onClick={onClose}><section ref={ref} className="tb-modal" role="dialog" aria-modal aria-label={title} onClick={e => e.stopPropagation()}><header><h2>{title}</h2><button onClick={onClose} className="tb-icon-button" aria-label="Cerrar"><X size={20} /></button></header>{children}</section></div>
}

/** Vista administrable de demostración: persistencia local explícita y ningún efecto en Tavus. */
export function TrainingBuilder({ demo = false }: { demo?: boolean }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const { levelId } = useParams()
  const base = demo ? '/admin/training/demo' : '/admin/training'
  const [programs, setPrograms] = useState<TrainingProgram[]>(readPrograms)
  const [programId, setProgramId] = useState(() => programs[0]!.id)
  const program = programs.find(p => p.id === programId) ?? programs[0]!
  const selected = programs.flatMap(p => p.levels).find(l => l.id === levelId)
  const [draft, setDraft] = useState<TrainingLevel | null>(selected ? structuredClone(selected) : null)
  const [tab, setTab] = useState<EditorTab>('general')
  const [view, setView] = useState<'levels' | 'agents'>('levels')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [toast, setToast] = useState('')
  const [errors, setErrors] = useState<string[]>([])
  const [agentModal, setAgentModal] = useState(false)
  const [preview, setPreview] = useState<TrainingLevel | null>(null)
  const [programModal, setProgramModal] = useState(false)
  const [newProgramName, setNewProgramName] = useState('')
  const [deleteLevel, setDeleteLevel] = useState<TrainingLevel | null>(null)
  const [resetModal, setResetModal] = useState(false)
  const [dragId, setDragId] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [storageWarning, setStorageWarning] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const dirty = draft && selected ? JSON.stringify(draft) !== JSON.stringify(selected) : false

  useEffect(() => {
    const level = programs.flatMap(p => p.levels).find(l => l.id === levelId)
    setDraft(level ? structuredClone(level) : null)
    setErrors([])
  }, [levelId, programs])
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(''), 3800)
    return () => clearTimeout(timer)
  }, [toast])
  useEffect(() => {
    function beforeUnload(e: BeforeUnloadEvent) { if (dirty) e.preventDefault() }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [dirty])
  useEffect(() => {
    function close(e: KeyboardEvent) { if (e.key === 'Escape') setPreview(null) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [])

  if (!demo && user?.role !== 'admin') return <div className="tb-access"><ShieldCheck size={36} /><h1>Acceso de administrador</h1><p>Este módulo se configura desde una cuenta de administración.</p><Link to="/inteligencia">Volver al panel</Link></div>

  function persist(next: TrainingProgram[], message: string) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      setStorageWarning(false)
      setToast(message)
    } catch {
      setStorageWarning(true)
      setToast('Cambio guardado en esta sesión. El navegador no permitió conservarlo al cerrar.')
    }
    setPrograms(next)
  }
  function change<K extends keyof TrainingLevel>(key: K, value: TrainingLevel[K]) {
    setDraft(d => d ? { ...d, [key]: value } : d)
    setErrors([])
  }
  function leave(callback: () => void) {
    if (!dirty || window.confirm('Tienes cambios sin guardar. ¿Salir del editor y descartarlos?')) callback()
  }
  function edit(level: TrainingLevel, editorTab: EditorTab = 'general') {
    leave(() => { setTab(editorTab); setView('levels'); navigate(base + '/' + level.id) })
  }
  function create(agentId?: string) {
    leave(() => {
      const level = newLevel()
      const agent = agents.find(a => a.id === agentId)
      if (agent) Object.assign(level, { agentId: agent.id, characterName: agent.name, specialty: agent.specialty, voice: agent.voice, voiceId: agent.voiceId })
      persist(programs.map(p => p.id === program.id ? { ...p, levels: [...p.levels, level] } : p), 'Nuevo borrador creado.')
      setView('levels'); setTab('general'); navigate(base + '/' + level.id)
    })
  }
  function save() {
    if (!draft) return
    const problems = validation(draft)
    if (problems.length) { setErrors(problems); return }
    setSaving(true)
    persist(programs.map(p => ({ ...p, levels: p.levels.map(l => l.id === draft.id ? structuredClone(draft) : l) })), 'Nivel guardado en esta demostración.')
    setSaving(false)
  }
  function updateObjective(id: string, patch: Partial<Objective>) {
    if (draft) change('objectives', draft.objectives.map(o => o.id === id ? { ...o, ...patch } : o))
  }
  function duplicate(level: TrainingLevel) {
    const copy = structuredClone(level)
    copy.id = crypto.randomUUID(); copy.name += ' · Copia'; copy.status = 'draft'
    copy.objectives = copy.objectives.map(o => ({ ...o, id: crypto.randomUUID() }))
    const index = program.levels.findIndex(l => l.id === level.id)
    const levels = [...program.levels]; levels.splice(index + 1, 0, copy)
    persist(programs.map(p => p.id === program.id ? { ...p, levels } : p), 'Copia creada como borrador.')
  }
  function reorder(fromId: string, toId: string) {
    const levels = [...program.levels]
    const from = levels.findIndex(l => l.id === fromId), to = levels.findIndex(l => l.id === toId)
    if (from < 0 || to < 0 || from === to) return
    const moved = levels.splice(from, 1)[0]!
    levels.splice(to, 0, moved)
    persist(programs.map(p => p.id === program.id ? { ...p, levels } : p), 'Orden de los niveles actualizado.')
  }
  async function uploadBackground(file: File | undefined) {
    if (!file) return
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 2 * 1024 * 1024) { setErrors(['Usa una imagen PNG, JPG o WebP de hasta 2 MB.']); return }
    const reader = new FileReader()
    reader.onload = () => { setDraft(d => d ? { ...d, background: 'personalizado', backgroundImage: String(reader.result) } : d); setErrors([]) }
    reader.onerror = () => setErrors(['No pudimos leer esa imagen. Intenta con otra.'])
    reader.readAsDataURL(file)
  }
  const activeObjectives = draft?.objectives.filter(o => o.active) ?? []
  const weightTotal = activeObjectives.reduce((sum, o) => sum + o.weight, 0)
  const weightValid = Math.abs(weightTotal - 100) < 0.01
  const levels = program.levels.filter(l => (filter === 'all' || l.status === filter) &&
    (l.name + ' ' + l.characterName).toLowerCase().includes(search.toLowerCase()))

  function editorContent(level: TrainingLevel) {
    switch (tab) {
      case 'general': return <>
        <SectionHeading title="El punto de partida" description="Dale una identidad clara a esta experiencia de entrenamiento." />
        <Input label="Nombre del nivel" value={level.name} onChange={v => change('name', v)} />
        <Textarea label="Descripción corta" value={level.description} onChange={v => change('description', v)} hint="Una frase para que el estudiante entienda qué va a practicar." rows={2} />
        <div className="tb-form-grid"><Select label="Dificultad" value={level.difficulty} onChange={v => change('difficulty', v)}>{['Básico', 'Intermedio', 'Avanzado', 'Experto'].map(d => <option key={d}>{d}</option>)}</Select><Input label="Duración máxima (minutos)" type="number" min={1} max={60} value={level.minutes} onChange={v => change('minutes', Number(v))} /></div>
        <Select label="Estado del nivel" value={level.status} onChange={v => change('status', v as TrainingLevel['status'])}><option value="draft">Borrador</option><option value="active">Activo</option><option value="inactive">Inactivo</option></Select>
        <Textarea label="Notas internas" value={level.internalDescription} onChange={v => change('internalDescription', v)} hint="Solo para el equipo de entrenamiento." />
        <div className="tb-inline-note"><ShieldCheck size={18} /><span>En esta demostración, activar un nivel solo cambia su estado visual.</span></div>
      </>
      case 'agent': return <>
        <SectionHeading title="Quién lleva la conversación" description="Elige el personaje y ajusta su forma de hablar y reaccionar." />
        <div className="tb-current-agent"><img src={(agents.find(a => a.id === level.agentId) ?? agents[0]!).photo} alt="" /><div><span className="tb-eyebrow">AGENTE ACTUAL</span><strong>{level.characterName}</strong><small>{level.specialty}</small></div><button className="tb-button tb-button--outline" onClick={() => setAgentModal(true)}>Cambiar agente</button></div>
        <div className="tb-form-grid"><Input label="Nombre del personaje" value={level.characterName} onChange={v => change('characterName', v)} /><Input label="Especialidad" value={level.specialty} onChange={v => change('specialty', v)} /></div>
        <Textarea label="Personalidad" value={level.personality} onChange={v => change('personality', v)} hint="Por ejemplo: directo, pragmático, ligeramente escéptico." />
        <Input label="Tono de conversación" value={level.tone} onChange={v => change('tone', v)} />
        <label className="tb-field"><span>Resistencia del personaje <b>{level.resistance}/5</b></span><input type="range" min="0" max="5" value={level.resistance} onChange={e => change('resistance', Number(e.target.value))} /><small>De colaborador a muy exigente. Ajusta la dificultad de la interacción.</small></label>
        <div className="tb-form-grid"><Select label="Voz · catálogo de ejemplo" value={level.voice} onChange={v => { change('voice', v); change('voiceId', agents.find(a => a.voice === v)?.voiceId ?? '') }}>{[...new Set(agents.map(a => a.voice))].map(v => <option key={v}>{v}</option>)}</Select><Select label="Idioma" value={level.language} onChange={v => change('language', v)}><option>Español · Colombia</option><option>Español · Neutro</option><option>Inglés</option></Select></div>
        <Textarea label="Saludo inicial" value={level.greeting} onChange={v => change('greeting', v)} rows={2} />
      </>
      case 'scenario': return <>
        <SectionHeading title="Una situación que se sienta real" description="Define qué está pasando y qué debe descubrir el estudiante." />
        <Textarea label="Contexto de la conversación" value={level.context} onChange={v => change('context', v)} hint="¿Dónde ocurre? ¿Qué hace el médico actualmente? ¿Cuál es la dificultad?" rows={4} />
        <Textarea label="Objetivo del estudiante" value={level.learnerGoal} onChange={v => change('learnerGoal', v)} />
        <Textarea label="Objeciones del personaje" value={level.objections} onChange={v => change('objections', v)} hint="Escribe una objeción por línea." />
        <div className="tb-hidden-information"><span><ShieldCheck size={18} /> Información que debe descubrir</span><Textarea label="Información reservada" value={level.hiddenInformation} onChange={v => change('hiddenInformation', v)} /><Textarea label="Cuándo puede revelarla" value={level.revealWhen} onChange={v => change('revealWhen', v)} rows={2} /></div>
        <h3 className="tb-subheading">Conocimiento disponible</h3><p className="tb-help">Selecciona los materiales de ejemplo que tendría disponibles este agente.</p>
        <div className="tb-material-list">{knowledgeMaterials.map(m => <label key={m}><FileText size={18} /><span>{m}</span><input type="checkbox" checked={level.knowledge.includes(m)} onChange={() => change('knowledge', level.knowledge.includes(m) ? level.knowledge.filter(k => k !== m) : [...level.knowledge, m])} /></label>)}</div>
      </>
      case 'objectives': return <>
        <SectionHeading title="Qué queremos que logre" description="Cada objetivo conecta el comportamiento del agente con una habilidad observable." />
        <div className="tb-objective-list">{level.objectives.map((o, i) => <article key={o.id} className={'tb-objective ' + (!o.active ? 'tb-objective--inactive' : '')}>
          <div className="tb-objective-header"><span className="tb-number">{String(i + 1).padStart(2, '0')}</span><strong>{o.name || 'Nuevo objetivo'}</strong><button className="tb-icon-button" aria-label={'Subir objetivo ' + o.name} disabled={i === 0} onClick={() => { const list = [...level.objectives]; [list[i - 1], list[i]] = [list[i]!, list[i - 1]!]; change('objectives', list) }}><ArrowUp size={15} /></button><button className="tb-icon-button" aria-label={'Bajar objetivo ' + o.name} disabled={i === level.objectives.length - 1} onClick={() => { const list = [...level.objectives]; [list[i + 1], list[i]] = [list[i]!, list[i + 1]!]; change('objectives', list) }}><ArrowDown size={15} /></button><button className="tb-icon-button tb-text-danger" aria-label={'Eliminar objetivo ' + o.name} onClick={() => change('objectives', level.objectives.filter(item => item.id !== o.id))}><Trash2 size={16} /></button></div>
          <Input label={'Nombre del objetivo ' + (i + 1)} value={o.name} onChange={v => updateObjective(o.id, { name: v })} />
          <Textarea label={'Descripción del objetivo ' + (i + 1)} value={o.description} onChange={v => updateObjective(o.id, { description: v })} rows={2} />
          <Toggle label="Objetivo activo" checked={o.active} onChange={() => updateObjective(o.id, { active: !o.active })} />
          <details className="tb-details"><summary>Comportamiento del agente para este objetivo <ChevronDown size={15} /></summary><Textarea label="Instrucción específica" value={o.prompt} onChange={v => updateObjective(o.id, { prompt: v })} /><Input label="Variables de salida" value={o.variables} onChange={v => updateObjective(o.id, { variables: v })} hint="Separadas por coma. Se conectarán con Objectives de Tavus." /></details>
        </article>)}</div>
        <button className="tb-button tb-button--outline tb-full" onClick={() => change('objectives', [...level.objectives, { id: crypto.randomUUID(), name: 'Nuevo objetivo', description: '', weight: 0, required: false, active: true, prompt: '', variables: '' }])}><Plus size={18} /> Agregar objetivo</button>
      </>
      case 'evaluation': return <>
        <SectionHeading title="Una evaluación a tu medida" description="Decide qué pesa más y qué acciones son indispensables para aprobar este nivel." />
        <div className="tb-score-intro"><div className="tb-score-icon"><ListChecks size={25} /></div><div><strong>Scorecard del nivel</strong><p>Las dimensiones se corresponden con los objetivos activos.</p></div><span className="tb-chip">0 – 100</span></div>
        <div className="tb-weight-table"><div className="tb-weight-head"><span>Dimensión de evaluación</span><span>Peso</span><span>Obligatorio</span></div>{activeObjectives.map(o => <div className="tb-weight-row" key={o.id}><div><strong>{o.name}</strong><small>{o.description}</small></div><label className="tb-weight-input"><input aria-label={'Peso de ' + o.name} type="number" min="0" max="100" step="1" value={o.weight} onChange={e => updateObjective(o.id, { weight: Number(e.target.value) })} /><span>%</span></label><input aria-label={o.name + ' obligatorio'} type="checkbox" checked={o.required} onChange={() => updateObjective(o.id, { required: !o.required })} /></div>)}<div className={'tb-weight-total ' + (weightValid ? 'is-valid' : 'is-invalid')} role="status"><span>{weightValid ? <CheckCircle2 size={18} /> : <Target size={18} />} {weightValid ? 'Pesos equilibrados' : 'Ajusta los pesos para sumar 100 %'}</span><strong>{Math.round(weightTotal * 100) / 100} / 100 %</strong></div></div>
        <div className="tb-passing"><div><h3>Puntaje mínimo para aprobar</h3><p>El estudiante también debe cumplir los objetivos marcados como obligatorios.</p></div><label><input aria-label="Puntaje mínimo para aprobar" type="number" min="0" max="100" value={level.passingScore} onChange={e => change('passingScore', Number(e.target.value))} /><span>/100</span></label></div>
        <div className="tb-inline-note"><ShieldCheck size={18} /><span>Un buen puntaje no compensa una acción crítica omitida. El resultado necesita evidencia de la conversación.</span></div>
        <details className="tb-details"><summary>Cómo se verá la retroalimentación <ChevronDown size={16} /></summary><div className="tb-feedback-example"><span className="tb-eyebrow">EJEMPLO · MANEJO DE OBJECIONES</span><strong>78 / 100</strong><p><b>Fortaleza:</b> Respondiste la objeción con un argumento concreto.</p><p><b>Mejora:</b> Confirma si quedó resuelta antes de continuar.</p><blockquote>“Entiendo que necesita una diferencia respaldada por evidencia.”</blockquote></div></details>
      </>
      case 'environment': return <>
        <SectionHeading title="El lugar también cuenta" description="Elige el contexto visual en el que ocurre la simulación." />
        <div className="tb-background-grid">{backgrounds.map(b => <button key={b.id} className={'tb-background-option ' + (level.background === b.id ? 'is-selected' : '')} onClick={() => { change('background', b.id); if (b.id !== 'personalizado') change('backgroundImage', '') }}><span className={'tb-room-mini tb-room-mini--' + b.id} style={{ backgroundColor: b.color }}><i /><i /><i />{level.background === b.id && <Check size={17} />}</span><strong>{b.name}</strong><small>{b.description}</small></button>)}</div>
        <input ref={fileRef} type="file" hidden accept="image/png,image/jpeg,image/webp" onChange={e => void uploadBackground(e.target.files?.[0])} />
        <button className="tb-button tb-button--outline tb-full" onClick={() => fileRef.current?.click()}><ImagePlus size={18} /> Subir imagen de fondo</button>
        {level.backgroundImage && <button className="tb-text-button" onClick={() => change('backgroundImage', '')}>Quitar imagen subida</button>}
        <div className="tb-form-grid"><Select label="Composición" value={level.layout} onChange={v => change('layout', v as TrainingLevel['layout'])}><option value="immersive">Inmersiva</option><option value="framed">Encuadre de conversación</option></Select><label className="tb-field"><span>Color de acento</span><div className="tb-color-field"><input type="color" value={level.accent} onChange={e => change('accent', e.target.value)} /><span>{level.accent.toUpperCase()}</span></div></label></div>
        <Toggle label="Mostrar marca Novamed" hint="Una presencia sutil dentro de la experiencia." checked={level.showBrand} onChange={() => change('showBrand', !level.showBrand)} />
        <p className="tb-help">La vista previa muestra el diseño del entorno. El reemplazo del fondo del video dependerá de la Face utilizada; Phoenix 4.5 todavía no lo admite.</p>
      </>
      case 'feedback': return <>
        <SectionHeading title="Convertir el resultado en aprendizaje" description="Una devolución clara y un siguiente paso para practicar mejor." />
        <Textarea label="Mensaje al superar el nivel" value={level.passedMessage} onChange={v => change('passedMessage', v)} />
        <Textarea label="Mensaje cuando necesita repetir" value={level.failedMessage} onChange={v => change('failedMessage', v)} />
        <Textarea label="Recomendación para el siguiente intento" value={level.recommendation} onChange={v => change('recommendation', v)} rows={4} />
        <div className="tb-inline-note"><Sparkles size={18} /><span>El feedback real deberá combinar fortalezas, mejoras y fragmentos de la conversación. Aquí puedes revisar su presentación.</span></div>
      </>
      case 'advanced': return <>
        <SectionHeading title="Los detalles detrás del personaje" description="Opciones técnicas preparadas para la siguiente etapa de integración." />
        <div className="tb-inline-note"><Video size={18} /><span>Los identificadores se muestran como referencia. Esta versión no consulta ni modifica recursos de Tavus.</span></div>
        <Input label="Face ID" value={(agents.find(a => a.id === level.agentId) ?? agents[0]!).faceId} readOnly onChange={() => {}} hint="Referencia del avatar seleccionado en el catálogo de ejemplo." />
        <Input label="PAL ID (opcional)" value={level.palId} onChange={v => change('palId', v)} />
        <Input label="Voice ID (opcional)" value={level.voiceId} onChange={v => change('voiceId', v)} />
        <Select label="Memoria de la experiencia" value={level.memory} onChange={v => change('memory', v as TrainingLevel['memory'])}><option value="off">Desactivada</option><option value="level">Dentro de este nivel</option><option value="program">Dentro del programa</option><option value="user">Continuidad por estudiante</option></Select>
        <Textarea label="Comportamiento del agente" value={level.behavior} onChange={v => change('behavior', v)} />
        <Textarea label="Restricciones" value={level.guardrails} onChange={v => change('guardrails', v)} rows={4} />
        <div className="tb-prompt-heading"><h3>Instrucciones completas</h3><button className="tb-text-button" onClick={() => change('systemPrompt', compilePrompt(level))}><WandSparkles size={15} /> Generar desde los campos</button></div>
        <Textarea label="System prompt" value={level.systemPrompt} onChange={v => change('systemPrompt', v)} rows={10} hint="Generación determinista del texto configurado. No utiliza un modelo de IA." />
      </>
    }
  }

  return (
    <div className="tb-app">
      <aside className="tb-sidebar">
        <Link to={base} className="tb-brand" onClick={e => { if (dirty) { e.preventDefault(); leave(() => navigate(base)) } }}>uno<span>.</span><small>ADMINISTRACIÓN</small></Link>
        <div className="tb-workspace"><span className="tb-workspace-logo">N</span><div><strong>Novamed</strong><small>Equipo de entrenamiento</small></div><ChevronDown size={15} /></div>
        <p className="tb-nav-label">ESPACIO DE TRABAJO</p>
        <nav>
          <button onClick={() => leave(() => { setView('levels'); navigate(base) })} className={view === 'levels' ? 'is-active' : ''}><GraduationCap size={20} /><span>Training Builder</span><i>Nuevo</i></button>
          <button onClick={() => leave(() => { setView('agents'); navigate(base) })} className={view === 'agents' ? 'is-active' : ''}><Users size={19} /><span>Biblioteca de agentes</span></button>
          <Link to={demo ? '/inteligencia/demo/resumen' : '/admin'} onClick={e => { if (dirty) { e.preventDefault(); leave(() => navigate(demo ? '/inteligencia/demo/resumen' : '/admin')) } }}><LayoutGrid size={19} /><span>Panel de administrador</span><ArrowRight size={15} /></Link>
        </nav>
        <div className="tb-sidebar-bottom"><div className="tb-preview-card"><Eye size={20} /><strong>Versión para presentar</strong><p>Explora, diseña y prueba el recorrido con datos de ejemplo.</p><button onClick={() => setResetModal(true)}><RotateCcw size={14} /> Restablecer ejemplo</button></div><div className="tb-admin-profile"><span>NA</span><div><strong>{demo ? 'Novamed · Admin' : user?.full_name}</strong><small>Administración de entrenamiento</small></div></div></div>
      </aside>
      <div className="tb-main">
        <header className="tb-topbar"><div><span>Administración</span><ChevronRight size={14} /><strong>Entrenamiento</strong>{draft && <><ChevronRight size={14} /><span className="tb-breadcrumb-level">{draft.name}</span></>}</div><span className="tb-demo-badge"><span /> DEMOSTRACIÓN</span></header>
        <div className="tb-demo-strip"><Eye size={15} /><span>Vista de presentación. Los cambios se guardan solo en este navegador; todavía no se publican en Tavus.</span></div>
        {storageWarning && <div className="tb-error" role="alert">El almacenamiento del navegador está bloqueado. Los cambios solo estarán disponibles durante esta sesión.</div>}
        {levelId && !selected ? <div className="tb-page-heading"><div><h1>Ese nivel no está en esta demostración</h1><p>Vuelve al programa para seleccionar otro.</p><button className="tb-button tb-button--primary" onClick={() => navigate(base)}>Ver niveles</button></div></div> : draft ? <>
          <div className="tb-editor-header"><div><button className="tb-back" onClick={() => leave(() => navigate(base))}><ArrowLeft size={16} /> Todos los niveles</button><h1>{draft.name}</h1><p><span className={'tb-status tb-status--' + draft.status}>{statusNames[draft.status]}</span><span>{dirty ? 'Cambios sin guardar' : 'Guardado en esta demo'}</span></p></div><div className="tb-header-actions"><button className="tb-button tb-button--outline" onClick={() => setPreview(draft)}><Play size={16} /> Probar escenario</button><button className="tb-button tb-button--primary" onClick={save} disabled={saving}>{saving ? <LoaderCircle size={17} /> : <Save size={17} />} Guardar nivel</button></div></div>
          <div className="tb-editor-layout">
            <nav className="tb-editor-nav" aria-label="Secciones del editor">{tabs.map(t => <button key={t.id} onClick={() => setTab(t.id)} aria-current={tab === t.id ? 'page' : undefined} className={tab === t.id ? 'is-active' : ''}><t.icon size={17} /><span>{t.label}</span>{tab === t.id && <ChevronRight size={14} />}</button>)}</nav>
            <section className="tb-editor-form" key={tab}>{errors.length > 0 && <div className="tb-error" role="alert">{errors.map(e => <p key={e}>{e}</p>)}</div>}{editorContent(draft)}</section>
            <aside className="tb-preview-pane"><div className="tb-preview-heading"><span className="tb-eyebrow">VISTA PREVIA</span><span><span /> En tiempo real</span></div><AgentStage level={draft} compact /><div className="tb-preview-info"><span className="tb-eyebrow">EXPERIENCIA DEL ESTUDIANTE</span><h3>{draft.name}</h3><p>{draft.description || 'Describe brevemente qué va a practicar el estudiante.'}</p><div className="tb-preview-meta"><span><SlidersHorizontal size={15} />{draft.difficulty}</span><span><Clock3 size={15} />{draft.minutes} min</span></div><div className="tb-preview-goal"><Target size={18} /><div><strong>Tu objetivo</strong><p>{draft.learnerGoal || 'Define el objetivo de esta simulación.'}</p></div></div><button className="tb-button tb-button--primary tb-full" onClick={() => setPreview(draft)}><Play size={16} /> Probar escenario</button><small>Recorrido de ejemplo · sin consumo de minutos</small></div><div className="tb-preview-checklist"><span><CheckCircle2 size={15} /> {activeObjectives.length} objetivos activos</span><span className={!weightValid ? 'tb-text-danger' : ''}><ListChecks size={15} /> Pesos: {Math.round(weightTotal * 100) / 100} %</span><span><ShieldCheck size={15} /> Aprobación: {draft.passingScore}/100</span></div></aside>
          </div>
        </> : view === 'agents' ? (
          <div className="tb-page-content"><div className="tb-page-heading"><div><span className="tb-eyebrow">BIBLIOTECA DE EJEMPLO</span><h1>Personajes con propósito</h1><p>La apariencia, la voz y la personalidad tienen trabajos distintos.</p></div></div><div className="tb-agent-library">{agents.map(a => <article key={a.id}><img src={a.photo} alt={a.name} /><div><span className="tb-chip">Agente virtual</span><h2>{a.name}</h2><p>{a.specialty}</p><span className="tb-agent-voice">Voz: {a.voice}</span><button className="tb-button tb-button--primary tb-full" onClick={() => create(a.id)}><Plus size={17} /> Crear nivel con este agente</button></div></article>)}</div><div className="tb-library-note"><ShieldCheck size={19} /><p>Catálogo visual de ejemplo. En la versión conectada, los agentes y las voces disponibles se consultarán desde la cuenta de Tavus.</p></div></div>
        ) : (
          <div className="tb-page-content">
            <div className="tb-page-heading"><div><span className="tb-eyebrow">DISEÑA CONVERSACIONES QUE ENSEÑAN</span><h1>Training Builder<span>.</span></h1><p>Una experiencia para cada habilidad. Un criterio claro para avanzar.</p></div><button className="tb-button tb-button--primary" onClick={() => create()}><Plus size={18} /> Crear nivel</button></div>
            <section className="tb-program-card"><div className="tb-program-icon"><GraduationCap size={28} /></div><div className="tb-program-info"><span className="tb-eyebrow">PROGRAMA DE ENTRENAMIENTO</span><select aria-label="Programa de entrenamiento" value={program.id} onChange={e => { setProgramId(e.target.value); setSearch(''); setFilter('all') }}>{programs.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select><p>{program.description}</p></div><div className="tb-program-stat"><strong>{program.levels.length}</strong><span>niveles</span></div><div className="tb-program-stat"><strong>{program.levels.filter(l => l.status === 'active').length}</strong><span>activos</span></div><button className="tb-icon-button" aria-label="Crear programa" onClick={() => setProgramModal(true)}><Plus size={20} /></button></section>
            <div className="tb-list-toolbar"><div><h2>Tu recorrido de entrenamiento</h2><p>Arrastra los niveles para cambiar el orden.</p></div><div className="tb-list-filters"><label className="tb-search"><Search size={16} /><input aria-label="Buscar nivel" placeholder="Buscar nivel o agente…" value={search} onChange={e => setSearch(e.target.value)} /></label><select aria-label="Filtrar estado" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">Todos los estados</option><option value="active">Activos</option><option value="draft">Borradores</option><option value="inactive">Inactivos</option></select></div></div>
            <div className="tb-level-grid">{levels.map(level => {
              const index = program.levels.findIndex(l => l.id === level.id)
              const agent = agents.find(a => a.id === level.agentId) ?? agents[0]!
              return <article key={level.id} className={'tb-level-card ' + (dragOver === level.id ? 'tb-level-card--drop' : '') + (level.status === 'inactive' ? ' tb-level-card--inactive' : '')} draggable={!search && filter === 'all'} onDragStart={e => { e.dataTransfer.setData('text/plain', level.id); e.dataTransfer.effectAllowed = 'move'; setDragId(level.id) }} onDragOver={e => { if (dragId) { e.preventDefault(); setDragOver(level.id) } }} onDrop={e => { e.preventDefault(); reorder(e.dataTransfer.getData('text/plain'), level.id); setDragOver(null); setDragId(null) }} onDragEnd={() => { setDragId(null); setDragOver(null) }}>
                <div className="tb-level-cover"><img src={agent.photo} alt={level.characterName} /><div className="tb-cover-shade" /><span className="tb-level-number">{String(index + 1).padStart(2, '0')}</span><span className={'tb-status tb-status--' + level.status}>{statusNames[level.status]}</span><GripVertical className="tb-drag-grip" size={19} aria-label="Arrastrar para reordenar" /><div className="tb-cover-agent"><strong>{level.characterName}</strong><small>{level.specialty}</small></div></div>
                <div className="tb-level-body"><div className="tb-level-meta"><span className={'tb-difficulty tb-difficulty--' + index}><i /><i /><i /><i /><span>{level.difficulty}</span></span><span><Clock3 size={14} /> {level.minutes} min</span></div><button className="tb-level-title" onClick={() => edit(level)}>{level.name}<ArrowRight size={18} /></button><p>{level.description || 'Una nueva experiencia lista para diseñar.'}</p><div className="tb-level-summary"><span><Target size={14} />{level.objectives.filter(o => o.active).length} objetivos</span><span><ShieldCheck size={14} />{level.passingScore}/100 para aprobar</span></div><div className="tb-card-actions"><button className="tb-card-edit" onClick={() => edit(level)}><Settings2 size={15} /> Editar nivel</button><button className="tb-icon-button" aria-label={'Duplicar ' + level.name} onClick={() => duplicate(level)}><Copy size={16} /></button><button className="tb-icon-button" aria-label={(level.status === 'active' ? 'Desactivar ' : 'Activar ') + level.name} onClick={() => persist(programs.map(p => p.id === program.id ? { ...p, levels: p.levels.map(l => l.id === level.id ? { ...l, status: l.status === 'active' ? 'inactive' : 'active' } : l) } : p), 'Estado actualizado en esta demo.')}>{level.status === 'active' ? <Pause size={16} /> : <Play size={16} />}</button><details className="tb-card-menu"><summary aria-label={'Más opciones de ' + level.name}><MoreHorizontal size={18} /></summary><div><button disabled={index === 0} onClick={() => reorder(level.id, program.levels[index - 1]!.id)}><ArrowUp size={14} /> Subir nivel</button><button disabled={index === program.levels.length - 1} onClick={() => reorder(level.id, program.levels[index + 1]!.id)}><ArrowDown size={14} /> Bajar nivel</button><button onClick={() => edit(level, 'evaluation')}><ListChecks size={14} /> Editar scorecard</button><button className="tb-text-danger" onClick={() => setDeleteLevel(level)}><Trash2 size={14} /> Eliminar nivel</button></div></details></div></div>
              </article>
            })}<button className="tb-add-level-card" onClick={() => create()}><span><Plus size={26} /></span><strong>La siguiente habilidad empieza aquí</strong><p>Crea un nuevo escenario para tu equipo.</p><b>Agregar nivel <ArrowRight size={15} /></b></button></div>
            {levels.length === 0 && <div className="tb-empty"><Search size={25} /><h3>{program.levels.length ? 'No encontramos niveles con ese filtro' : 'Diseña tu primer nivel'}</h3><p>{program.levels.length ? 'Prueba con otro nombre o cambia el estado.' : 'Define el personaje, el objetivo y cómo se evaluará la conversación.'}</p></div>}
            <div className="tb-bottom-note"><ShieldCheck size={16} /><span>Diseña a tu ritmo. Los borradores de esta demo no afectan a los estudiantes.</span><button onClick={() => create()}>Crear otro nivel <ArrowRight size={14} /></button></div>
          </div>
        )}
      </div>
      {toast && <div className="tb-toast" role="status"><CheckCircle2 size={18} />{toast}</div>}
      {agentModal && draft && <Modal title="Elige el agente de este nivel" onClose={() => setAgentModal(false)}><p className="tb-help">Catálogo de presentación · no conectado con Tavus.</p><div className="tb-agent-picker">{agents.map(a => <button key={a.id} className={draft.agentId === a.id ? 'is-selected' : ''} onClick={() => { setDraft(d => d ? { ...d, agentId: a.id, characterName: a.name, specialty: a.specialty, voice: a.voice, voiceId: a.voiceId } : d); setAgentModal(false) }}><img src={a.photo} alt="" /><strong>{a.name}</strong><small>{a.specialty}</small>{draft.agentId === a.id && <CheckCircle2 size={19} />}</button>)}</div><p className="tb-help">La creación de nuevos agentes se incorporará al conectar el módulo con Tavus.</p></Modal>}
      {preview && <ScenarioPreview level={preview} onClose={() => setPreview(null)} />}
      {programModal && <Modal title="Crear programa de entrenamiento" onClose={() => setProgramModal(false)}><Input label="Nombre del programa" value={newProgramName} onChange={setNewProgramName} /><button className="tb-button tb-button--primary tb-full" disabled={!newProgramName.trim()} onClick={() => { const p: TrainingProgram = { id: crypto.randomUUID(), name: newProgramName.trim(), description: 'Diseña un recorrido a la medida de tu equipo.', levels: [] }; persist([...programs, p], 'Programa creado en esta demostración.'); setProgramId(p.id); setNewProgramName(''); setProgramModal(false) }}><Plus size={17} /> Crear programa</button></Modal>}
      {deleteLevel && <Modal title="Eliminar nivel de la demostración" onClose={() => setDeleteLevel(null)}><p>Se eliminará <strong>{deleteLevel.name}</strong> de este navegador. Los niveles del entrenamiento real seguirán intactos.</p><div className="tb-modal-actions"><button className="tb-button tb-button--outline" onClick={() => setDeleteLevel(null)}>Cancelar</button><button className="tb-button tb-button--danger" onClick={() => { persist(programs.map(p => ({ ...p, levels: p.levels.filter(l => l.id !== deleteLevel.id) })), 'Nivel eliminado de la demo.'); setDeleteLevel(null) }}><Trash2 size={16} /> Eliminar de la demo</button></div></Modal>}
      {resetModal && <Modal title="Restablecer la demostración" onClose={() => setResetModal(false)}><p>Volverás a los cuatro niveles de ejemplo. Se descartarán los programas y cambios guardados en este navegador.</p><div className="tb-modal-actions"><button className="tb-button tb-button--outline" onClick={() => setResetModal(false)}>Cancelar</button><button className="tb-button tb-button--primary" onClick={() => { const initial = initialPrograms(); persist(initial, 'Demostración restablecida.'); setProgramId(initial[0]!.id); setResetModal(false); setView('levels'); navigate(base) }}><RotateCcw size={16} /> Restablecer</button></div></Modal>}
    </div>
  )
}
