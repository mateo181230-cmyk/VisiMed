import clsx from 'clsx'
import { ArrowLeft, CheckCircle2, CircleAlert, Quote, RefreshCw, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { type PracticeAttempt, type PracticeEvaluation, training } from '../../api/client'
import { Button, Card, Notice, SectionTitle, Skeleton } from '../../components/ui'
import { BAND_TONE, TONE_CLASS, trainingError } from './labels'

const POLL_MS = 2000
const WAITING = new Set(['starting', 'live', 'ended'])
const CHECK_LABEL: Record<string, string> = { si: 'Sí', parcial: 'Parcialmente', no: 'No' }

function CompetencyBar({ c }: { c: PracticeEvaluation['competencies'][number] }) {
  const pct = (c.score / c.max) * 100
  return (
    <li className="space-y-1.5 px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-semibold">{c.name}</span>
        <span className="font-bold tabular-nums">
          {c.score}/{c.max}
        </span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-line"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={c.max}
        aria-valuenow={c.score}
        aria-label={`${c.name}: ${c.score} de ${c.max}`}
      >
        <div
          className={clsx('h-full rounded-full', pct >= 80 ? 'bg-ok' : pct >= 50 ? 'bg-brand' : 'bg-warn')}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-sm text-muted">{c.comment}</p>
    </li>
  )
}

function Evaluation({ attempt, evaluation }: { attempt: PracticeAttempt; evaluation: PracticeEvaluation }) {
  const tone = BAND_TONE[evaluation.band.level] ?? 'muted'
  const t = evaluation.training
  return (
    <div className="space-y-6">
      <Card className="space-y-3 p-5">
        <div className="flex items-end justify-between gap-4">
          <p className="text-5xl leading-none font-extrabold tracking-tight tabular-nums">
            {evaluation.total}
            <span className="text-2xl font-bold text-muted">/{evaluation.max}</span>
          </p>
          {attempt.delta !== null && attempt.delta !== undefined && (
            <span className="text-sm font-semibold text-muted tabular-nums">
              {attempt.delta === 0
                ? 'Igual que el intento anterior'
                : `${attempt.delta > 0 ? `+${attempt.delta}` : attempt.delta} frente al intento anterior`}
            </span>
          )}
        </div>
        <span className={clsx('inline-block rounded-md px-2.5 py-1 text-sm font-bold', TONE_CLASS[tone])}>
          {evaluation.band.label}
        </span>
        {evaluation.preliminary && (
          <p className="text-sm text-muted">
            Calificación preliminar por reglas. La evaluación con IA la afinará cuando esté activa.
          </p>
        )}
      </Card>

      <Card className="space-y-3 p-5">
        <p className="flex items-center gap-2 text-lg font-bold">
          {t.approved ? (
            <CheckCircle2 size={24} className="text-ok" aria-hidden />
          ) : (
            <CircleAlert size={24} className="text-warn" aria-hidden />
          )}
          {t.approved ? 'Escenario aprobado' : 'Aún no aprobado'}
        </p>
        <p className="text-[15px]">{t.diagnosis}</p>
        <ul className="space-y-1.5">
          {t.requirements.map((r) => (
            <li key={r.id} className="flex items-start gap-2 text-[15px]">
              {r.met ? (
                <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-ok" aria-label="Cumplido" />
              ) : (
                <XCircle size={18} className="mt-0.5 shrink-0 text-warn" aria-label="Pendiente" />
              )}
              <span>{r.text}</span>
            </li>
          ))}
        </ul>
        {!t.approved && (
          <p className="rounded-control bg-brand-50 px-3.5 py-3 text-[15px] text-navy">
            <span className="font-semibold">Para el próximo intento: </span>
            {t.practice}
          </p>
        )}
      </Card>

      {evaluation.improvements.length > 0 && (
        <section className="space-y-2">
          <SectionTitle>Mejora esto</SectionTitle>
          <Card className="space-y-2 p-4">
            {evaluation.critical_errors.slice(0, 2).map((e) => (
              <p key={e.id} className="flex items-start gap-2 text-[15px]">
                <CircleAlert size={18} className="mt-0.5 shrink-0 text-warn" aria-hidden />
                <span>
                  {e.text}
                  {e.kind === 'compliance' && <span className="ml-1 text-xs font-bold text-warn">(cumplimiento)</span>}
                </span>
              </p>
            ))}
            {evaluation.critical_errors.length === 0 &&
              evaluation.improvements.map((item) => (
                <p key={item} className="text-[15px]">
                  {item}
                </p>
              ))}
          </Card>
        </section>
      )}

      {evaluation.key_moment && (
        <section className="space-y-2">
          <SectionTitle>Momento clave</SectionTitle>
          <Card className="space-y-2 p-4">
            <p className="flex gap-2 text-[15px] italic">
              <Quote size={18} className="mt-0.5 shrink-0 text-muted" aria-hidden />«{evaluation.key_moment.quote}»
            </p>
            <p className="text-sm text-muted">{evaluation.key_moment.why}</p>
          </Card>
        </section>
      )}

      {evaluation.best_response && (
        <section className="space-y-2">
          <SectionTitle>Mejor respuesta aprobada</SectionTitle>
          <Card className="space-y-2 p-4">
            <p className="text-[15px]">«{evaluation.best_response.text}»</p>
            <p className="text-sm text-muted">
              {evaluation.best_response.area} · Fuente: {evaluation.best_response.source}
            </p>
          </Card>
        </section>
      )}

      <section className="space-y-2">
        <SectionTitle>Por competencia</SectionTitle>
        <Card className="overflow-hidden">
          <ul className="divide-y divide-line">
            {evaluation.competencies.map((c) => (
              <CompetencyBar key={c.id} c={c} />
            ))}
          </ul>
        </Card>
      </section>

      {evaluation.strengths.length > 0 && (
        <section className="space-y-2">
          <SectionTitle>Lo hiciste bien</SectionTitle>
          <Card className="space-y-2 p-4">
            {evaluation.strengths.map((s) => (
              <p key={s} className="flex items-start gap-2 text-[15px]">
                <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-ok" aria-hidden />
                <span>{s}</span>
              </p>
            ))}
          </Card>
        </section>
      )}

      <details className="rounded-card bg-white shadow-[0_1px_2px_rgba(16,24,40,0.06)]">
        <summary className="min-h-14 cursor-pointer px-4 py-4 font-semibold">Evaluación específica del caso</summary>
        <ul className="divide-y divide-line border-t border-line">
          {evaluation.case_checks.map((c) => (
            <li key={c.id} className="flex items-start justify-between gap-3 px-4 py-3 text-[15px]">
              <span>{c.text}</span>
              <span className="shrink-0 font-semibold">{CHECK_LABEL[c.value] ?? c.value}</span>
            </li>
          ))}
        </ul>
      </details>

      <p className="text-[15px] text-muted">{evaluation.feedback}</p>

      {attempt.transcript.length > 0 && (
        <details className="rounded-card bg-white shadow-[0_1px_2px_rgba(16,24,40,0.06)]">
          <summary className="min-h-14 cursor-pointer px-4 py-4 font-semibold">Transcripción de la visita</summary>
          <ol className="space-y-2 border-t border-line px-4 py-3 text-[15px]">
            {attempt.transcript.map((line, i) => (
              <li key={i}>
                <span className="font-semibold">{line.role === 'doctor' ? 'Médico: ' : 'Tú: '}</span>
                {line.text}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  )
}

/** Resultado de una práctica: espera la evaluación y la muestra (doc 04 §6.3, pantalla 6). */
export function ResultScreen() {
  const { attemptId = '' } = useParams()
  const navigate = useNavigate()
  const [attempt, setAttempt] = useState<PracticeAttempt | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tries, setTries] = useState(0)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null
    const tick = async () => {
      const res = await training.attempt(attemptId)
      if (cancelled) return
      if (!res.ok) {
        setError(trainingError(res))
        return
      }
      setAttempt(res.data)
      if (WAITING.has(res.data.status)) {
        setTries((n) => n + 1)
        timer = setTimeout(() => void tick(), POLL_MS)
      }
    }
    void tick()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [attemptId])

  const again = () => attempt && navigate(`/entrenar/${attempt.scenario_slug}`)

  return (
    <div className="space-y-6 px-5 pt-[calc(12px+var(--safe-top))] pb-6">
      <Link
        to={attempt ? `/entrenar/${attempt.scenario_slug}` : '/entrenar'}
        className="-ml-1 inline-flex min-h-11 items-center gap-1 font-semibold text-brand"
      >
        <ArrowLeft size={20} /> {attempt?.scenario_title ?? 'Entrenar'}
      </Link>
      <div>
        <h1 className="text-[28px] leading-tight font-extrabold tracking-tight">Tu visita</h1>
        {attempt && (
          <p className="text-muted">
            {attempt.doctor_name} · {attempt.doctor_specialty}
          </p>
        )}
      </div>

      {error ? (
        <Card className="space-y-4 p-6 text-center">
          <p className="text-muted">{error}</p>
          <Button variant="soft" icon={<RefreshCw size={18} />} onClick={() => window.location.reload()}>
            Reintentar
          </Button>
        </Card>
      ) : !attempt || WAITING.has(attempt.status) ? (
        <div className="space-y-4" aria-busy>
          <Notice>
            {tries > 45
              ? 'La transcripción está tardando más de lo normal. Puedes salir: el resultado quedará en «Tus intentos».'
              : 'Evaluando tu visita…'}
          </Notice>
          <Skeleton className="h-28" />
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : attempt.status === 'evaluated' && attempt.evaluation ? (
        <Evaluation attempt={attempt} evaluation={attempt.evaluation} />
      ) : attempt.status === 'no_transcript' ? (
        <Card className="space-y-2 p-6 text-center">
          <p className="text-lg font-bold">No quedó conversación para evaluar</p>
          <p className="text-muted">Esta visita no cuenta como intento. Habla al menos un par de turnos con el médico.</p>
        </Card>
      ) : (
        <Card className="space-y-2 p-6 text-center">
          <p className="text-lg font-bold">La visita no se pudo iniciar</p>
          <p className="text-muted">No cuenta como intento. Inténtalo de nuevo en un momento.</p>
        </Card>
      )}

      {attempt && !WAITING.has(attempt.status) && (
        <div className="flex flex-col gap-3">
          <Button block size="lg" onClick={again}>
            Practicar otra vez
          </Button>
          <Button block variant="ghost" onClick={() => navigate('/entrenar')}>
            Volver a Entrenar
          </Button>
        </div>
      )}
    </div>
  )
}
