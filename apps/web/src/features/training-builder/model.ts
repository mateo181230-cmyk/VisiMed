/** Estado exclusivo de la demostración. No escribe en la API ni inicia conversaciones de Tavus. */
export type LevelStatus = 'draft' | 'active' | 'inactive'
export type EditorTab = 'general' | 'agent' | 'scenario' | 'objectives' | 'evaluation' | 'environment' | 'feedback' | 'advanced'

export interface DemoAgent {
  id: string
  name: string
  specialty: string
  photo: string
  faceId: string
  voice: string
  voiceId: string
}

export interface Objective {
  id: string
  name: string
  description: string
  weight: number
  required: boolean
  active: boolean
  prompt: string
  variables: string
}

export interface TrainingLevel {
  id: string
  name: string
  description: string
  internalDescription: string
  difficulty: string
  minutes: number
  status: LevelStatus
  agentId: string
  characterName: string
  specialty: string
  personality: string
  tone: string
  resistance: number
  objections: string
  context: string
  learnerGoal: string
  hiddenInformation: string
  revealWhen: string
  greeting: string
  behavior: string
  guardrails: string
  objectives: Objective[]
  passingScore: number
  background: string
  backgroundImage: string
  accent: string
  layout: 'immersive' | 'framed'
  showBrand: boolean
  memory: 'off' | 'level' | 'program' | 'user'
  voice: string
  voiceId: string
  language: string
  palId: string
  knowledge: string[]
  passedMessage: string
  failedMessage: string
  recommendation: string
  systemPrompt: string
}

export interface TrainingProgram {
  id: string
  name: string
  description: string
  levels: TrainingLevel[]
}

export const agents: DemoAgent[] = [
  { id: 'andres', name: 'Dr. Andrés Gómez', specialty: 'Medicina general', photo: '/entrenar/r621a6013477.jpg', faceId: 'r621a6013477', voice: 'Horacio', voiceId: '57D8YIbQSuE3REDPO6Vm' },
  { id: 'internista', name: 'Dra. Carolina Peña', specialty: 'Medicina interna', photo: '/entrenar/rc6fedbe63ea.jpg', faceId: 'rc6fedbe63ea', voice: 'Diana García', voiceId: 'irla3teuChAApguKnzms' },
  { id: 'gastro', name: 'Dr. Camilo Restrepo', specialty: 'Gastroenterología', photo: '/entrenar/rff4f230c435.jpg', faceId: 'rff4f230c435', voice: 'Yohan', voiceId: 'qdU62IMovREYmfk9SQ4K' },
  { id: 'formulador', name: 'Dra. Lucía Mancera', specialty: 'Medicina general / interna', photo: '/entrenar/rb68659d2f28.jpg', faceId: 'rb68659d2f28', voice: 'Clau', voiceId: 'SplyIQAjgy4DKGAnOrHi' },
]

export const backgrounds = [
  { id: 'consultorio', name: 'Consultorio', description: 'Un espacio cercano y profesional', color: '#dce9e7' },
  { id: 'hospital', name: 'Hospital', description: 'Un entorno clínico de alta exigencia', color: '#dce5f1' },
  { id: 'oficina', name: 'Oficina', description: 'Conversaciones de negocio', color: '#ede7dc' },
  { id: 'farmacia', name: 'Farmacia', description: 'Asesoría en el punto de atención', color: '#e0e9dd' },
  { id: 'corporativo', name: 'Corporativo', description: 'La identidad de tu organización', color: '#dce0ee' },
  { id: 'personalizado', name: 'Personalizado', description: 'Sube tu propia imagen', color: '#ece5ef' },
]

export const knowledgeMaterials = ['Ficha técnica ESOMED', 'Brochure de producto', 'Estudio clínico', 'Argumentario de objeciones', 'Políticas comerciales']
export const STORAGE_KEY = 'uno.training-builder.demo.v1'

export function defaultObjectives(): Objective[] {
  return [
    { id: crypto.randomUUID(), name: 'Descubrimiento', description: 'Identificar la necesidad y el criterio de prescripción del médico.', weight: 20, required: true, active: true, prompt: 'Permite que el visitador descubra la necesidad haciendo preguntas. No entregues la respuesta por iniciativa propia.', variables: 'need_identified, need_description' },
    { id: crypto.randomUUID(), name: 'Argumentación', description: 'Conectar la propuesta de valor con la necesidad identificada.', weight: 25, required: true, active: true, prompt: 'Escucha la propuesta de valor y pide precisión cuando sea genérica.', variables: 'product_presented, value_proposition' },
    { id: crypto.randomUUID(), name: 'Manejo de objeciones', description: 'Responder con evidencia y confirmar si la objeción quedó resuelta.', weight: 30, required: true, active: true, prompt: 'Presenta una objeción pertinente y mantén la resistencia hasta recibir una respuesta concreta.', variables: 'objection_detected, objection_handled' },
    { id: crypto.randomUUID(), name: 'Cierre', description: 'Acordar un próximo paso concreto y realista.', weight: 25, required: false, active: true, prompt: 'Acepta un próximo paso solo cuando la conversación lo justifique.', variables: 'next_step_requested, next_step_agreed' },
  ]
}

export function newLevel(): TrainingLevel {
  return {
    id: crypto.randomUUID(), name: 'Nuevo nivel', description: '', internalDescription: '', difficulty: 'Básico', minutes: 5, status: 'draft',
    agentId: agents[0]!.id, characterName: agents[0]!.name, specialty: agents[0]!.specialty,
    personality: 'Directo, pragmático y cordial.', tone: 'Profesional, natural y breve.', resistance: 2,
    objections: 'No veo una diferencia clínica.\nYa trabajo con otro laboratorio.',
    context: '', learnerGoal: '', hiddenInformation: '', revealWhen: '',
    greeting: 'Buenos días. Tengo unos minutos antes de mi siguiente paciente, ¿en qué puedo ayudarte?',
    behavior: 'Responde en una o dos frases. Permite que el visitador lleve la conversación.',
    guardrails: 'No inventar evidencia clínica.\nNo revelar información oculta sin una pregunta pertinente.\nNo mencionar pacientes reales.',
    objectives: defaultObjectives(), passingScore: 70, background: 'consultorio', backgroundImage: '',
    accent: '#1668f0', layout: 'immersive', showBrand: true, memory: 'off',
    voice: agents[0]!.voice, voiceId: agents[0]!.voiceId, language: 'Español · Colombia', palId: '',
    knowledge: ['Ficha técnica ESOMED', 'Argumentario de objeciones'],
    passedMessage: 'Nivel superado. Tu conversación fue clara y pertinente.',
    failedMessage: 'Aún hay oportunidades. Repasa la recomendación y vuelve a practicar.',
    recommendation: 'En el próximo intento, confirma la necesidad antes de presentar el producto.', systemPrompt: '',
  }
}

export function initialPrograms(): TrainingProgram[] {
  const titles = ['Explorar antes de presentar', 'Construir un argumento relevante', 'Responder con evidencia', 'Manejar la comparación']
  const descriptions = ['Primera visita a un médico sin preferencia clara de tratamiento.', 'Una internista ocupada que exige una propuesta concreta.', 'Un especialista escéptico frente a las afirmaciones generales.', 'Una médica que ya prescribe un producto de la competencia.']
  return [{
    id: 'esomed', name: 'Visita médica · ESOMED', description: 'De la primera pregunta a una conversación que genera confianza.',
    levels: titles.map((name, i) => ({
      ...newLevel(), id: 'level-' + (i + 1), name, description: descriptions[i]!,
      status: 'active', agentId: agents[i]!.id, characterName: agents[i]!.name, specialty: agents[i]!.specialty,
      voice: agents[i]!.voice, voiceId: agents[i]!.voiceId,
      difficulty: ['Básico', 'Intermedio', 'Avanzado', 'Experto'][i]!, minutes: [5, 5, 8, 8][i]!,
      resistance: i + 1, context: descriptions[i]!,
      learnerGoal: ['Descubrir cómo prescribe el médico antes de hablar del producto.', 'Presentar una propuesta de valor conectada con el perfil del paciente.', 'Sustentar la diferenciación sin exagerar los beneficios.', 'Responder una objeción y acordar un próximo paso.'][i]!,
      hiddenInformation: 'Estaría dispuesto a considerar el producto si recibe evidencia clínica pertinente.',
      revealWhen: 'El visitador pregunta por el criterio clínico y presenta soporte concreto.',
      passingScore: [70, 75, 80, 80][i]!,
    })),
  }]
}

function isLevel(value: unknown): value is TrainingLevel {
  if (!value || typeof value !== 'object') return false
  const level = value as Partial<TrainingLevel>
  return typeof level.id === 'string' && typeof level.name === 'string' && typeof level.agentId === 'string' &&
    typeof level.passingScore === 'number' && typeof level.minutes === 'number' &&
    Array.isArray(level.objectives) && level.objectives.every(o =>
      o && typeof o.id === 'string' && typeof o.name === 'string' && typeof o.weight === 'number',
    ) && Array.isArray(level.knowledge)
}

export function readPrograms(): TrainingProgram[] {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null')
    if (Array.isArray(raw) && raw.length > 0 && raw.every(p =>
      p && typeof p.id === 'string' && typeof p.name === 'string' && Array.isArray(p.levels) && p.levels.every(isLevel),
    )) return raw as TrainingProgram[]
  } catch { /* Almacenamiento bloqueado o una demostración anterior: vuelve al ejemplo. */ }
  return initialPrograms()
}

export function validation(level: TrainingLevel): string[] {
  const problems: string[] = []
  if (!level.name.trim()) problems.push('Escribe el nombre del nivel.')
  if (!Number.isFinite(level.minutes) || level.minutes < 1 || level.minutes > 60) problems.push('La duración debe ser de 1 a 60 minutos.')
  if (!Number.isFinite(level.passingScore) || level.passingScore < 0 || level.passingScore > 100) problems.push('La aprobación debe estar entre 0 y 100.')
  const active = level.objectives.filter(o => o.active)
  if (!active.length) problems.push('Agrega al menos un objetivo activo.')
  if (active.some(o => !o.name.trim() || !Number.isFinite(o.weight) || o.weight < 0 || o.weight > 100)) problems.push('Revisa los nombres y pesos de los objetivos.')
  if (Math.abs(active.reduce((sum, o) => sum + o.weight, 0) - 100) > 0.01) problems.push('Los pesos de los objetivos activos deben sumar 100 %.')
  return problems
}

export function compilePrompt(level: TrainingLevel): string {
  return [
    'Participas como un médico virtual en una simulación de entrenamiento.',
    'Personaje: ' + level.characterName + '. Especialidad: ' + level.specialty + '.',
    'Personalidad: ' + level.personality, 'Tono: ' + level.tone,
    'Contexto: ' + level.context, 'Comportamiento: ' + level.behavior,
    'Resistencia: ' + level.resistance + ' de 5.',
    'Objeciones:\n' + level.objections,
    'Información reservada: ' + level.hiddenInformation, 'Revelarla cuando: ' + level.revealWhen,
    'Restricciones:\n' + level.guardrails,
  ].join('\n\n')
}
