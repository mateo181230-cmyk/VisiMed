import clsx from 'clsx'
import { CheckCircle2, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { type QuizResult, type TrainingScenario, training } from '../../api/client'
import { Sheet } from '../../components/Sheet'
import { Button, Notice } from '../../components/ui'
import { trainingError } from './labels'

/**
 * Formulario de preparación (doc 04 §6.4): preguntas de elección única con la explicación y la fuente
 * inmediatas. No bloquea la visita; su resultado solo sirve de diagnóstico.
 */
export function QuizSheet({
  scenario,
  open,
  onClose,
  onDone,
}: {
  scenario: TrainingScenario
  open: boolean
  onClose: () => void
  onDone: (result: QuizResult) => void
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [result, setResult] = useState<QuizResult | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setAnswers({})
      setResult(null)
      setError(null)
    }
  }, [open])

  const complete = scenario.quiz.every((q) => answers[q.id])
  const byQuestion = new Map(result?.results.map((r) => [r.question_id, r]) ?? [])

  async function submit() {
    setSending(true)
    setError(null)
    const res = await training.submitQuiz(scenario.slug, answers)
    setSending(false)
    if (!res.ok) {
      setError(trainingError(res))
      return
    }
    setResult(res.data)
    onDone(res.data)
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Formulario de preparación"
      footer={
        result ? (
          <Button block size="lg" onClick={onClose}>
            Listo
          </Button>
        ) : (
          <Button block size="lg" disabled={!complete || sending} onClick={() => void submit()}>
            {sending ? 'Revisando…' : 'Revisar mis respuestas'}
          </Button>
        )
      }
    >
      <div className="space-y-5 pt-1">
        {result ? (
          <Notice tone={result.passed ? 'ok' : 'warn'}>
            <strong>
              {result.correct} de {result.total} correctas.
            </strong>{' '}
            {result.message}
          </Notice>
        ) : (
          <p className="text-[15px] text-muted">Responde sin consultar la lectura: así ves qué reforzar antes de hablar.</p>
        )}
        {error && <Notice tone="danger">{error}</Notice>}
        {scenario.quiz.map((q, index) => {
          const graded = byQuestion.get(q.id)
          return (
            <fieldset key={q.id} className="space-y-2">
              <legend className="mb-2 font-semibold">
                {index + 1}. {q.question}
              </legend>
              {q.options.map((o) => {
                const chosen = answers[q.id] === o.id
                const isCorrect = graded?.correct_option === o.id
                return (
                  <label
                    key={o.id}
                    className={clsx(
                      'flex min-h-12 cursor-pointer items-start gap-3 rounded-control border px-3.5 py-3 text-[15px]',
                      graded
                        ? isCorrect
                          ? 'border-ok bg-ok-50'
                          : chosen
                            ? 'border-warn bg-warn-50'
                            : 'border-line'
                        : chosen
                          ? 'border-brand bg-brand-50'
                          : 'border-line bg-white',
                    )}
                  >
                    <input
                      type="radio"
                      name={q.id}
                      value={o.id}
                      checked={chosen}
                      disabled={Boolean(result)}
                      onChange={() => setAnswers((a) => ({ ...a, [q.id]: o.id }))}
                      className="mt-1 size-4 accent-[var(--color-brand)]"
                    />
                    <span className="flex-1">{o.text}</span>
                    {graded && isCorrect && <CheckCircle2 size={20} className="shrink-0 text-ok" aria-label="Correcta" />}
                    {graded && chosen && !isCorrect && (
                      <XCircle size={20} className="shrink-0 text-warn" aria-label="Tu respuesta" />
                    )}
                  </label>
                )
              })}
              {graded && (
                <p className="rounded-control bg-canvas px-3.5 py-2.5 text-[15px]">
                  {graded.explanation} <span className="text-sm text-muted">Fuente: {graded.source}.</span>
                </p>
              )}
            </fieldset>
          )
        })}
      </div>
    </Sheet>
  )
}
