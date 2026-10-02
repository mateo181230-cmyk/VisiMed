import clsx from 'clsx'
import { ArrowLeft, BookOpen, ChevronRight, ClipboardCheck, Mic, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { type TrainingScenario, training } from '../../api/client'
import { Button, Card, Notice, SectionTitle, Skeleton } from '../../components/ui'
import { DEFAULT_TZ } from '../../lib/time'
import { useAuth } from '../auth/AuthProvider'
import { ConsentSheet } from './ConsentSheet'
import { discardPreparedCall, preloadDailyClient, prepareDailyCall } from './dailyClient'
import { QuizSheet } from './QuizSheet'
import { BAND_TONE, TONE_CLASS, doctorNotice, faceUrl, formatDateTime, progressPill, trainingError } from './labels'
import { checkMicrophone, micHelp } from './microphone'

const BAND_LABEL: Record<string, string> = {
  sobresaliente: 'Sobresaliente',
  bueno: 'Bueno',
  intermedio: 'Intermedio',
  deficiente: 'Deficiente',
}

function AttemptLine({ attempt, tz }: { attempt: TrainingScenario['attempts'][number]; tz: string }) {
  const live = attempt.status === 'live' || attempt.status === 'starting'
  const to = live ? `/entrenar/visita/${attempt.id}` : `/entrenar/intento/${attempt.id}`
  let detail: React.ReactNode
  if (attempt.status === 'evaluated' && attempt.total !== null && attempt.total !== undefined) {
    const tone = BAND_TONE[attempt.band ?? ''] ?? 'muted'
    detail = (
      <>
        <span className="font-bold tabular-nums">{attempt.total}/30</span>
        <span className={clsx('rounded-md px-2 py-0.5 text-xs font-bold', TONE_CLASS[tone])}>
          {BAND_LABEL[attempt.band ?? ''] ?? attempt.band}
        </span>
        {attempt.approved && <span className="text-xs font-bold text-ok">Aprobado</span>}
      </>
    )
  } else if (live) {
    detail = <span className="font-semibold text-brand">En curso</span>
  } else {
    detail = <span className="text-muted">Sin conversación para evaluar</span>
  }
  return (
    <Link to={to} className="flex min-h-14 items-center gap-3 px-4 py-3 active:bg-canvas">
      <span className="w-[112px] shrink-0 text-[15px] text-muted tabular-nums">{formatDateTime(attempt.created_at, tz)}</span>
      <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2 text-[15px]">{detail}</span>
      <ChevronRight size={20} className="shrink-0 text-muted" aria-hidden />
    </Link>
  )
}

/** Un escenario (doc 04 §6.3): objetivo, dificultad y contexto; preparación; visita; intentos. */
export function ScenarioScreen() {
  const { slug = '' } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const tz = user?.timezone ?? DEFAULT_TZ
  const [data, setData] = useState<TrainingScenario | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [quizOpen, setQuizOpen] = useState(false)
  const [consentOpen, setConsentOpen] = useState(false)
  const [audioOnly, setAudioOnly] = useState(false)
  const [startPhase, setStartPhase] = useState<'microphone' | 'connection' | 'doctor' | null>(null)
  const [startProblem, setStartProblem] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    const res = await training.scenario(slug)
    if (res.ok) setData(res.data)
    else setError(trainingError(res))
  }, [slug])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (data?.doctor.mode === 'tavus' && data.doctor.status === 'available') {
      void preloadDailyClient().catch(() => {})
    }
  }, [data?.doctor.mode, data?.doctor.status])

  async function startVisit(consented = false) {
    if (!data) return
    setStartProblem(null)
    if (!consented && !data.profile.consent_accepted) {
      setConsentOpen(true)
      return
    }
    setStartPhase('microphone')
    if (data.doctor.mode !== 'fake') {
      const mic = await checkMicrophone()
      if (mic !== 'ok') {
        setStartPhase(null)
        setStartProblem(micHelp(mic))
        return
      }
      setStartPhase('connection')
      try {
        await prepareDailyCall()
      } catch (error) {
        setStartPhase(null)
        setStartProblem(error instanceof Error ? error.message : 'No pudimos cargar la videollamada.')
        return
      }
    }
    setStartPhase('doctor')
    const res = await training.start(data.slug, audioOnly)
    setStartPhase(null)
    if (!res.ok) {
      await discardPreparedCall()
      if ((res.kind === 'client' || res.kind === 'server') && res.code === 'attempt_active') {
        setStartProblem('Ya tienes una visita de práctica en curso. Termínala antes de empezar otra.')
      } else {
        setStartProblem(trainingError(res))
      }
      void load()
      return
    }
    navigate(`/entrenar/visita/${res.data.id}`, { state: { attempt: res.data } })
  }

  if (error)
    return (
      <div className="space-y-4 px-5 pt-[calc(16px+var(--safe-top))]">
        <Link to="/entrenar" className="inline-flex min-h-11 items-center gap-1 font-semibold text-brand">
          <ArrowLeft size={20} /> Entrenar
        </Link>
        <Card className="space-y-4 p-6 text-center">
          <p className="text-lg font-bold">No pudimos abrir este escenario</p>
          <p className="text-muted">{error}</p>
          <Button variant="soft" icon={<RefreshCw size={18} />} onClick={() => void load()}>
            Reintentar
          </Button>
        </Card>
      </div>
    )

  if (!data)
    return (
      <div className="space-y-4 px-5 pt-[calc(16px+var(--safe-top))]" aria-busy>
        <Skeleton className="h-8 w-28" />
        <Skeleton className="aspect-video" />
        <Skeleton className="h-40" />
      </div>
    )

  const notice = doctorNotice(data.doctor)
  const canStart = notice ? notice.canStart : true
  const pill = progressPill(data.progress.status)
  const photo = faceUrl(data.face_id)

  return (
    <div className="space-y-6 px-5 pt-[calc(12px+var(--safe-top))] pb-6">
      <Link to="/entrenar" className="-ml-1 inline-flex min-h-11 items-center gap-1 font-semibold text-brand">
        <ArrowLeft size={20} /> Entrenar
      </Link>

      <Card className="overflow-hidden">
        {photo && <img src={photo} alt={`Foto de ${data.doctor_name}`} className="aspect-video w-full object-cover" />}
        <div className="space-y-1 p-4">
          <p className="text-sm font-semibold text-muted">
            {data.doctor_name} · {data.doctor_specialty}
          </p>
          <h1 className="text-[26px] leading-tight font-extrabold tracking-tight">{data.title}</h1>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <span className={clsx('rounded-md px-2 py-0.5 text-xs font-bold', TONE_CLASS[pill.tone])}>{pill.text}</span>
            {data.progress.best !== null && data.progress.best !== undefined && (
              <span className="text-sm font-semibold text-muted tabular-nums">Mejor {data.progress.best}/30</span>
            )}
          </div>
        </div>
      </Card>

      <section className="space-y-2">
        <SectionTitle>Antes de entrar</SectionTitle>
        <Card>
          <dl className="divide-y divide-line">
            <div className="px-4 py-3">
              <dt className="text-sm font-semibold text-muted">Objetivo</dt>
              <dd className="mt-0.5">{data.objective}. {data.instruction}</dd>
            </div>
            <div className="px-4 py-3">
              <dt className="text-sm font-semibold text-muted">Dificultad</dt>
              <dd className="mt-0.5">
                {data.difficulty_label} · unos {data.minutes} minutos
              </dd>
            </div>
            <div className="px-4 py-3">
              <dt className="text-sm font-semibold text-muted">Contexto</dt>
              <dd className="mt-0.5">{data.barrier}</dd>
            </div>
          </dl>
        </Card>
      </section>

      <section className="space-y-2">
        <SectionTitle>Preparación</SectionTitle>
        <Card className="divide-y divide-line overflow-hidden">
          <details className="group">
            <summary className="flex min-h-14 cursor-pointer list-none items-center gap-3 px-4 py-3 active:bg-canvas">
              <BookOpen size={22} className="shrink-0 text-brand" aria-hidden />
              <span className="flex-1">
                <span className="block font-semibold">Lectura</span>
                <span className="block text-sm text-muted">{data.lesson.title}</span>
              </span>
              <ChevronRight size={20} className="shrink-0 text-muted transition-transform group-open:rotate-90" aria-hidden />
            </summary>
            <div className="space-y-4 px-4 pb-4 text-[15px]">
              <p>{data.lesson.intro}</p>
              <ol className="space-y-3">
                {data.lesson.blocks.map((block, i) => (
                  <li key={block.title}>
                    <p className="font-semibold">
                      {i + 1}. {block.title}
                    </p>
                    <p className="text-muted">{block.text}</p>
                  </li>
                ))}
              </ol>
              <p className="rounded-control bg-brand-50 px-3.5 py-3 text-navy">
                <span className="font-semibold">Ejemplo: </span>
                {data.lesson.example}
              </p>
              <div>
                <p className="font-semibold">Evita</p>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-muted">
                  {data.lesson.avoid.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
              <p className="text-sm text-muted">Fuente: {data.lesson.sources.join(' · ')}.</p>
            </div>
          </details>
          <button
            type="button"
            onClick={() => setQuizOpen(true)}
            className="flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left active:bg-canvas"
          >
            <ClipboardCheck size={22} className="shrink-0 text-brand" aria-hidden />
            <span className="flex-1">
              <span className="block font-semibold">Formulario de {data.quiz.length} preguntas</span>
              <span className="block text-sm text-muted">
                {data.last_quiz
                  ? `Último resultado: ${data.last_quiz.correct} de ${data.last_quiz.total}`
                  : 'Comprueba que reconoces la técnica antes de hablar'}
              </span>
            </span>
            <ChevronRight size={20} className="shrink-0 text-muted" aria-hidden />
          </button>
        </Card>
      </section>

      <section className="space-y-2">
        <SectionTitle>Visita con el médico</SectionTitle>
        <Card className="space-y-4 p-4">
          {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
          <p className="text-[15px] text-muted">
            Habla como en una visita real. El médico reacciona a lo que dices: pide brevedad, objeta y no acepta
            cifras sin soporte. Al terminar verás tu evaluación con la rúbrica de Novamed.
          </p>
          {data.doctor.mode !== 'fake' && (
            <label className="flex min-h-12 items-center gap-3 text-[15px]">
              <input
                type="checkbox"
                checked={audioOnly}
                onChange={(e) => setAudioOnly(e.target.checked)}
                className="size-5 accent-[var(--color-brand)]"
              />
              Solo voz, sin video del médico (usa menos datos)
            </label>
          )}
          {startProblem && <Notice tone="warn">{startProblem}</Notice>}
          <Button
            block
            size="lg"
            icon={<Mic size={22} />}
            disabled={!canStart || startPhase !== null}
            onClick={() => void startVisit()}
          >
            {startPhase === 'microphone' ? 'Comprobando micrófono…' : startPhase === 'connection' ? 'Conectando la videollamada…' : startPhase === 'doctor' ? 'Abriendo la visita…' : 'Empezar visita'}
          </Button>
        </Card>
      </section>

      {data.attempts.length > 0 && (
        <section className="space-y-2">
          <SectionTitle>Tus intentos</SectionTitle>
          <Card className="divide-y divide-line overflow-hidden">
            {data.attempts.map((attempt) => (
              <AttemptLine key={attempt.id} attempt={attempt} tz={tz} />
            ))}
          </Card>
        </section>
      )}

      <QuizSheet
        scenario={data}
        open={quizOpen}
        onClose={() => setQuizOpen(false)}
        onDone={(result) =>
          setData((d) => (d ? { ...d, last_quiz: { correct: result.correct, total: result.total, at: new Date().toISOString() } } : d))
        }
      />
      <ConsentSheet
        profile={data.profile}
        open={consentOpen}
        onClose={() => setConsentOpen(false)}
        onAccepted={(profile) => {
          setConsentOpen(false)
          setData((d) => (d ? { ...d, profile } : d))
          void startVisit(true)
        }}
      />
    </div>
  )
}
