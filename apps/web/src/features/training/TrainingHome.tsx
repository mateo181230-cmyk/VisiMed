import clsx from 'clsx'
import { ChevronRight, GraduationCap, PhoneCall, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { type TrainingOverview, training } from '../../api/client'
import { ScreenHeader } from '../../components/ScreenHeader'
import { ProfileLink } from '../../components/ProfileLink'
import { Button, Card, Notice, SectionTitle, Skeleton } from '../../components/ui'
import { TONE_CLASS, doctorNotice, faceUrl, progressPill, trainingError } from './labels'

export function useTrainingOverview() {
  const [data, setData] = useState<TrainingOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    setError(null)
    const res = await training.overview()
    if (res.ok) setData(res.data)
    else setError(trainingError(res))
  }, [])
  useEffect(() => {
    void load()
  }, [load])
  return { data, error, reload: load }
}

export function DoctorPhoto({ faceId, name, className }: { faceId: string; name: string; className?: string }) {
  const src = faceUrl(faceId)
  return src ? (
    <img src={src} alt={`Foto de ${name}`} className={clsx('shrink-0 object-cover', className)} loading="lazy" />
  ) : null
}

/** Entrenar (doc 04 §6.3): la lista de escenarios, el siguiente sugerido y si el médico está disponible. */
export function TrainingHome() {
  const navigate = useNavigate()
  const { data, error, reload } = useTrainingOverview()
  const notice = data ? doctorNotice(data.doctor) : null
  const suggested = data?.scenarios.find((s) => s.slug === data.suggested_slug) ?? null

  return (
    <>
      <ScreenHeader title="Entrenar" subtitle="Practica la visita de ESOMED con un médico virtual" right={<ProfileLink />} />
      <div className="space-y-6 px-5 pb-6">
        {error ? (
          <Card className="space-y-4 p-6 text-center">
            <p className="text-lg font-bold">No pudimos cargar tu entrenamiento</p>
            <p className="text-muted">{error}</p>
            <Button variant="soft" icon={<RefreshCw size={18} />} onClick={() => void reload()}>
              Reintentar
            </Button>
          </Card>
        ) : !data ? (
          <div className="space-y-4" aria-busy>
            <Skeleton className="h-24" />
            <Skeleton className="h-64" />
          </div>
        ) : (
          <>
            {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}

            {data.active_attempt_id && (
              <Link
                to={`/entrenar/visita/${data.active_attempt_id}`}
                className="flex min-h-14 items-center gap-3 rounded-card bg-brand-50 px-4 py-3 text-navy active:bg-brand-100"
              >
                <PhoneCall size={22} className="shrink-0 text-brand" aria-hidden />
                <span className="flex-1 font-semibold">Tienes una visita de práctica en curso</span>
                <span className="font-bold text-brand">Volver</span>
              </Link>
            )}

            {suggested && (
              <Card className="overflow-hidden">
                <div className="flex items-center gap-4 p-4">
                  <DoctorPhoto
                    faceId={suggested.face_id}
                    name={suggested.doctor_name}
                    className="size-16 rounded-full"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-muted">Siguiente práctica sugerida</p>
                    <p className="text-lg leading-snug font-bold">{suggested.title}</p>
                    <p className="text-[15px] text-muted">
                      {suggested.doctor_name} · {suggested.doctor_specialty}
                    </p>
                  </div>
                </div>
                <div className="px-4 pb-4">
                  <Button block size="lg" onClick={() => navigate(`/entrenar/${suggested.slug}`)}>
                    {suggested.progress.attempts > 0 ? 'Seguir practicando' : 'Empezar'}
                  </Button>
                </div>
              </Card>
            )}

            <section className="space-y-2">
              <SectionTitle>Escenarios</SectionTitle>
              <Card className="divide-y divide-line overflow-hidden">
                {data.scenarios.map((s) => {
                  const pill = progressPill(s.progress.status)
                  return (
                    <Link
                      key={s.slug}
                      to={`/entrenar/${s.slug}`}
                      className="flex min-h-[84px] items-center gap-3 px-4 py-3 active:bg-canvas"
                    >
                      <DoctorPhoto faceId={s.face_id} name={s.doctor_name} className="size-12 rounded-full" />
                      <span className="min-w-0 flex-1">
                        <span className="block leading-snug font-semibold">{s.title}</span>
                        <span className="block truncate text-sm text-muted">
                          {s.doctor_name} · {s.difficulty_label}
                        </span>
                        <span className="mt-1.5 flex flex-wrap items-center gap-2">
                          <span className={clsx('rounded-md px-2 py-0.5 text-xs font-bold', TONE_CLASS[pill.tone])}>
                            {pill.text}
                          </span>
                          {s.difficulty !== 'basico' && s.progress.best !== null && s.progress.best !== undefined && (
                            <span className="text-xs font-semibold text-muted tabular-nums">
                              Mejor {s.progress.best}/30
                            </span>
                          )}
                          {s.quiz && (
                            <span className="text-xs text-muted tabular-nums">
                              Formulario {s.quiz.correct}/{s.quiz.total}
                            </span>
                          )}
                        </span>
                      </span>
                      <ChevronRight size={20} className="shrink-0 text-muted" aria-hidden />
                    </Link>
                  )
                })}
              </Card>
            </section>

            <p className="flex items-start gap-2 px-1 text-sm text-muted">
              <GraduationCap size={18} className="mt-0.5 shrink-0" aria-hidden />
              Cada visita de práctica dura hasta 5 minutos. La calificación sigue la rúbrica de Novamed y tu
              gerente puede ver tus resultados.
            </p>
          </>
        )}
      </div>
    </>
  )
}
