import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  ApiResult,
  PracticeAttempt,
  QuizResult,
  TrainingOverview,
  TrainingProfile,
  TrainingScenario,
} from '../../api/client'
import { LiveVisitScreen } from './LiveVisitScreen'
import { ResultScreen } from './ResultScreen'
import { ScenarioScreen } from './ScenarioScreen'
import { TrainingHome } from './TrainingHome'

const connection = vi.hoisted(() => ({ prepareDailyCall: vi.fn(), discardPreparedCall: vi.fn(), preloadDailyClient: vi.fn() }))
vi.mock('./dailyClient', () => ({ ...connection, acquireDailyCall: vi.fn(), releaseDailyCall: vi.fn() }))
vi.mock('./microphone', () => ({ checkMicrophone: vi.fn(async () => 'ok'), micHelp: vi.fn() }))

const api = vi.hoisted(() => ({
  overview: vi.fn<() => Promise<ApiResult<TrainingOverview>>>(),
  scenario: vi.fn<(slug: string) => Promise<ApiResult<TrainingScenario>>>(),
  submitQuiz: vi.fn<(slug: string, answers: Record<string, string>) => Promise<ApiResult<QuizResult>>>(),
  saveProfile: vi.fn<(body: object) => Promise<ApiResult<TrainingProfile>>>(),
  start: vi.fn<(slug: string, audioOnly?: boolean) => Promise<ApiResult<PracticeAttempt>>>(),
  attempt: vi.fn<(id: string) => Promise<ApiResult<PracticeAttempt>>>(),
  end: vi.fn<(id: string) => Promise<ApiResult<PracticeAttempt>>>(),
}))

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return { ...actual, training: api }
})

vi.mock('../auth/AuthProvider', () => ({
  useAuth: () => ({ user: { id: 'u1', full_name: 'Ana Rep', role: 'rep', phone: '+57', timezone: 'America/Bogota' } }),
}))

const ok = <T,>(data: T): ApiResult<T> => ({ ok: true, data })

const profile = (accepted = false): TrainingProfile => ({
  salutation: accepted ? 'doctora' : null,
  consent_accepted: accepted,
  consent_version: 'v1',
  consent_text: 'Tu voz se transmite a Tavus y a ElevenLabs durante la visita.',
})

const offDoctor = {
  status: 'off',
  code: 'off',
  message: 'El médico virtual todavía no está activo. Mientras tanto puedes hacer la preparación.',
  mode: 'off',
} as const
const fakeDoctor = { status: 'available', code: null, message: null, mode: 'fake' } as const

const card = (slug: string, order: number, title: string, status: 'sin_practicar' | 'practicado' | 'aprobado') => ({
  slug,
  order,
  title,
  skill: 'Sondeo y escucha',
  segment: 'Segmento',
  difficulty: 'intermedio' as const,
  difficulty_label: 'Intermedio',
  doctor_name: `Dr. ${title}`,
  doctor_specialty: 'Medicina General',
  doctor_gender: 'M' as const,
  face_id: 'r621a6013477',
  minutes: 3,
  progress: {
    status,
    attempts: status === 'sin_practicar' ? 0 : 2,
    best: status === 'sin_practicar' ? null : 24,
    last: null,
    last_at: null,
  },
  quiz: status === 'sin_practicar' ? null : { correct: 3, total: 4 },
})

function overview(doctor: TrainingOverview['doctor'] = offDoctor): TrainingOverview {
  return {
    doctor,
    profile: profile(),
    suggested_slug: 'internista_exigente',
    active_attempt_id: null,
    scenarios: [
      card('medico_general_indiferenciado', 1, 'Explorar antes de presentar', 'aprobado'),
      card('internista_exigente', 2, 'Construir diferenciación clínica', 'sin_practicar'),
    ],
  }
}

function scenario(doctor: TrainingScenario['doctor'] = offDoctor, accepted = false): TrainingScenario {
  return {
    ...card('medico_general_indiferenciado', 1, 'Explorar antes de presentar', 'sin_practicar'),
    promise: 'Descubrir cómo prescribe el médico.',
    instruction: 'Haz preguntas antes de presentar.',
    objective: 'Lograr recordación y diferenciación simple',
    barrier: 'Percibe que todos los IBP son muy parecidos entre sí.',
    expected_close: 'Recordación de ESOMED',
    lesson: {
      title: 'La visita comienza entendiendo',
      intro: 'Antes de hablar de ESOMED descubre cómo decide.',
      blocks: [
        { title: 'Abre con una pregunta útil', text: 'Pregunta cómo decide.' },
        { title: 'Profundiza una vez', text: 'Pregunta qué pesa más.' },
        { title: 'Confirma lo que entendiste', text: 'Parafrasea.' },
      ],
      example: 'Doctor, ¿cómo suele definir cuál IBP formular?',
      avoid: ['Nombrar ESOMED antes de explorar.'],
      sources: ['Flujo de visita esperado'],
    },
    quiz: [
      {
        id: 'q1',
        question: '¿Cuál es la mejor forma de iniciar esta visita?',
        options: [
          { id: 'a', text: 'Presentar las ventajas de ESOMED.' },
          { id: 'b', text: 'Preguntar cómo decide qué IBP formular.' },
        ],
      },
    ],
    last_quiz: null,
    attempts: [],
    doctor,
    profile: profile(accepted),
    approval: { min_total: 18, min_competencies: { sondeo: 4 }, blocking_errors: [] },
  }
}

function attempt(overrides: Partial<PracticeAttempt> = {}): PracticeAttempt {
  return {
    id: 'a1',
    scenario_slug: 'medico_general_indiferenciado',
    scenario_title: 'Explorar antes de presentar',
    doctor_name: 'Dr. Andrés Gómez',
    doctor_specialty: 'Medicina General',
    face_id: 'r621a6013477',
    status: 'live',
    mode: 'fake',
    conversation_url: 'fake:c1',
    audio_only: false,
    max_seconds: 300,
    greeting: 'Sí, doctora, cuénteme, pero breve por favor.',
    created_at: '2026-09-29T12:00:00Z',
    ended_at: null,
    error_code: null,
    evaluation: null,
    delta: null,
    transcript: [],
    ...overrides,
  }
}

const evaluation: NonNullable<PracticeAttempt['evaluation']> = {
  method: 'reglas',
  preliminary: true,
  total: 24,
  max: 30,
  band: { level: 'bueno', label: 'Buen desempeño con oportunidades de mejora' },
  competencies: [
    { id: 'apertura', name: 'Apertura', score: 5, max: 5, comment: 'Abriste con un saludo profesional.', evaluated: true },
    { id: 'sondeo', name: 'Sondeo', score: 3, max: 5, comment: 'Faltó profundizar.', evaluated: true },
  ],
  critical_errors: [{ id: 'exagera_beneficios', text: 'Exageró beneficios o hizo afirmaciones absolutas', kind: 'compliance' }],
  case_checks: [{ id: 'detecto_perfil', text: '¿Detectó el perfil?', value: 'parcial' }],
  strengths: ['Apertura de visita: abriste bien.'],
  improvements: ['Identificación de necesidad: faltó profundizar.'],
  recommendation: 'Haz dos preguntas.',
  key_moment: { turn: 4, quote: 'Se absorbe más del 95%.', why: 'Afirmación absoluta o cifra sin soporte.' },
  best_response: { id: 'SONDEO_1', text: 'Doctor, ¿cómo suele definir cuál IBP formular?', source: 'Mensajes clave §5', area: 'Sondeo' },
  feedback: 'La visita estuvo bien estructurada.',
  training: {
    approved: false,
    requirements: [{ id: 'total', text: 'Puntaje total mínimo: 18/30', met: true }],
    diagnosis: 'Brecha de ejecución: reconoces la técnica, pero aún no la sostienes bajo presión.',
    focus: 'sondeo',
    practice: 'Prepara dos preguntas.',
  },
  quiz: { correct: 4, total: 4 },
  turns: 8,
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/entrenar" element={<TrainingHome />} />
        <Route path="/entrenar/:slug" element={<ScenarioScreen />} />
        <Route path="/entrenar/intento/:attemptId" element={<ResultScreen />} />
        <Route path="/entrenar/visita/:attemptId" element={<LiveVisitScreen />} />
      </Routes>
    </MemoryRouter>,
  )
  return userEvent.setup()
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset())
  Object.values(connection).forEach((fn) => fn.mockReset().mockResolvedValue(undefined))
})

describe('Entrenar · inicio', () => {
  it('muestra los escenarios con su estado, el sugerido y que el médico aún no está activo', async () => {
    api.overview.mockResolvedValue(ok(overview()))
    renderAt('/entrenar')
    expect(await screen.findByText('Siguiente práctica sugerida')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('todavía no está activo')
    expect(screen.getByText('Aprobado')).toBeInTheDocument()
    expect(screen.getByText('Sin practicar')).toBeInTheDocument()
    expect(screen.getByText('Mejor 24/30')).toBeInTheDocument()
    expect(screen.queryByText(/nivel dominado|trofeo|racha/i)).not.toBeInTheDocument()
  })

  it('sin conexión lo dice y ofrece reintentar', async () => {
    api.overview.mockResolvedValue({ ok: false, kind: 'network' })
    renderAt('/entrenar')
    expect(await screen.findByText(/Necesitas conexión para entrenar/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeInTheDocument()
  })
})

describe('Entrenar · escenario', () => {
  it('explica la presentación inicial sin prometer objeciones en básico', async () => {
    api.scenario.mockResolvedValue(ok({ ...scenario(), difficulty: 'basico', difficulty_label: 'Básico' }))
    renderAt('/entrenar/medico_general_indiferenciado')
    expect(await screen.findByText(/Practica un saludo, una presentación breve del producto y un cierre/)).toBeInTheDocument()
    expect(screen.queryByText(/pide brevedad, objeta/)).not.toBeInTheDocument()
  })

  it('no abre una conversación de pago si la videollamada no puede cargar', async () => {
    const doctor = { ...fakeDoctor, mode: 'tavus' as const }
    api.scenario.mockResolvedValue(ok(scenario(doctor, true)))
    connection.prepareDailyCall.mockRejectedValue(new Error('No pudimos cargar la videollamada.'))
    const user = renderAt('/entrenar/medico_general_indiferenciado')
    await user.click(await screen.findByRole('button', { name: 'Empezar visita' }))
    expect(await screen.findByText('No pudimos cargar la videollamada.')).toBeInTheDocument()
    expect(api.start).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Empezar visita' })).toBeEnabled()
  })

  it('el formulario se revisa con la explicación y la visita queda desactivada si el médico no está', async () => {
    api.scenario.mockResolvedValue(ok(scenario()))
    api.submitQuiz.mockResolvedValue(
      ok({
        correct: 0,
        total: 1,
        passed: false,
        message: 'Revisa las explicaciones antes de hablar con el médico.',
        results: [
          {
            question_id: 'q1',
            chosen: 'a',
            correct_option: 'b',
            is_correct: false,
            explanation: 'Primero necesitas comprender la práctica del médico.',
            source: 'Flujo de visita esperado, paso 1',
            skill: 'apertura',
          },
        ],
      }),
    )
    const user = renderAt('/entrenar/medico_general_indiferenciado')
    expect(await screen.findByRole('button', { name: /Empezar visita/ })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: /Formulario de 1 preguntas/ }))
    const dialog = await screen.findByRole('dialog')
    const review = within(dialog).getByRole('button', { name: 'Revisar mis respuestas' })
    expect(review).toBeDisabled()
    await user.click(within(dialog).getByLabelText('Presentar las ventajas de ESOMED.'))
    await user.click(review)
    expect(api.submitQuiz).toHaveBeenCalledWith('medico_general_indiferenciado', { q1: 'a' })
    expect(await within(dialog).findByText(/0 de 1 correctas/)).toBeInTheDocument()
    expect(within(dialog).getByText(/Primero necesitas comprender/)).toBeInTheDocument()
  })

  it('la primera visita pide el trato y las condiciones, y luego abre la visita', async () => {
    api.scenario.mockResolvedValue(ok(scenario(fakeDoctor)))
    api.saveProfile.mockResolvedValue(ok(profile(true)))
    api.start.mockResolvedValue(ok(attempt()))
    api.attempt.mockResolvedValue(ok(attempt()))
    const user = renderAt('/entrenar/medico_general_indiferenciado')
    await user.click(await screen.findByRole('button', { name: /Empezar visita/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Antes de tu primera visita' })
    const accept = within(dialog).getByRole('button', { name: 'Acepto y empiezo' })
    expect(accept).toBeDisabled()
    await user.click(within(dialog).getByRole('button', { name: 'Doctora' }))
    await user.click(accept)
    expect(api.saveProfile).toHaveBeenCalledWith({ salutation: 'doctora', accept_consent: true })
    await waitFor(() => expect(api.start).toHaveBeenCalledWith('medico_general_indiferenciado', false))
    expect(await screen.findByText(/Modo de prueba: no hay médico real/)).toBeInTheDocument()
  })
})

describe('Entrenar · visita y resultado', () => {
  it('básico no presenta como calificaciones las técnicas que no se evalúan', async () => {
    api.attempt.mockResolvedValue(ok(attempt({ status: 'evaluated', delta: 3, evaluation: {
      ...evaluation,
      improvements: [],
      competencies: [
        { id: 'apertura', name: 'Apertura', score: 4, max: 5, comment: 'Saludo breve.', evaluated: true },
        { id: 'sondeo', name: 'Sondeo', score: 5, max: 5, comment: 'Se trabaja en los niveles siguientes.', evaluated: false },
      ],
    } })))
    renderAt('/entrenar/intento/a1')
    expect(await screen.findByText('No se evalúa en este nivel')).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Apertura: 4 de 5' })).toBeInTheDocument()
    expect(screen.queryByRole('meter', { name: /Sondeo/ })).not.toBeInTheDocument()
    expect(screen.queryByText('5/5')).not.toBeInTheDocument()
    expect(screen.queryByText('/30')).not.toBeInTheDocument()
    expect(screen.queryByText(/frente al intento anterior/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Puntaje total mínimo/)).not.toBeInTheDocument()
    expect(screen.getByText('Exageró beneficios o hizo afirmaciones absolutas')).toBeInTheDocument()
  })

  it('en modo de prueba, «Terminar visita» cierra y muestra la evaluación', async () => {
    api.attempt
      .mockResolvedValueOnce(ok(attempt()))
      .mockResolvedValue(ok(attempt({ status: 'evaluated', conversation_url: null, evaluation, delta: 3 })))
    api.end.mockResolvedValue(ok(attempt({ status: 'evaluated', evaluation })))
    const user = renderAt('/entrenar/visita/a1')
    expect(await screen.findByText('Sí, doctora, cuénteme, pero breve por favor.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Terminar visita/ }))
    await waitFor(() => expect(api.end).toHaveBeenCalledWith('a1'))
    expect(await screen.findByText('Buen desempeño con oportunidades de mejora')).toBeInTheDocument()
    expect(screen.getByText('+3 frente al intento anterior')).toBeInTheDocument()
    expect(screen.getByText(/Calificación preliminar por reglas/)).toBeInTheDocument()
    expect(screen.getByText('Aún no aprobado')).toBeInTheDocument()
    expect(screen.getByText(/Se absorbe más del 95%/)).toBeInTheDocument()
    expect(screen.getByText(/Doctor, ¿cómo suele definir cuál IBP formular\?/)).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Sondeo: 3 de 5' })).toBeInTheDocument()
  })

  it('una visita sin conversación no cuenta como intento', async () => {
    api.attempt.mockResolvedValue(ok(attempt({ status: 'no_transcript', conversation_url: null })))
    renderAt('/entrenar/intento/a1')
    expect(await screen.findByText('No quedó conversación para evaluar')).toBeInTheDocument()
    expect(screen.getByText(/no cuenta como intento/)).toBeInTheDocument()
  })
})
