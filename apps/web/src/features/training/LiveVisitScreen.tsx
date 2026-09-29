import clsx from 'clsx'
import { Captions, Mic, MicOff, PhoneOff } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { type PracticeAttempt, training } from '../../api/client'
import { Button } from '../../components/ui'
import { faceUrl, formatSeconds, trainingError } from './labels'
import { type Caption, useTavusCall, useWakeLock } from './useTavusCall'

function useElapsed(since: number | null): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (since === null) return
    const id = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(id)
  }, [since])
  return since === null ? 0 : Math.max(0, (now - since) / 1000)
}

function CaptionLine({ caption }: { caption: Caption | null }) {
  if (!caption) return null
  return (
    <p className="mx-auto max-w-[440px] rounded-control bg-black/55 px-3.5 py-2 text-center text-[15px] leading-snug text-white">
      <span className="font-semibold">{caption.who === 'doctor' ? 'Médico: ' : 'Tú: '}</span>
      {caption.text}
    </p>
  )
}

/**
 * La visita (doc 04 §5.10): el médico a pantalla completa en vertical y dos botones. Sin barra
 * inferior ni nada que distraiga. Termina con «Terminar visita», por tiempo o si el médico cuelga.
 */
export function LiveVisitScreen() {
  const { attemptId = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const initial = (location.state as { attempt?: PracticeAttempt } | null)?.attempt ?? null
  const [attempt, setAttempt] = useState<PracticeAttempt | null>(initial?.id === attemptId ? initial : null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [showCaptions, setShowCaptions] = useState(true)
  const [ending, setEnding] = useState(false)
  const [wasHidden, setWasHidden] = useState(false)
  const finishing = useRef(false)

  useEffect(() => {
    if (attempt) return
    void (async () => {
      const res = await training.attempt(attemptId)
      if (res.ok) setAttempt(res.data)
      else setLoadError(trainingError(res))
    })()
  }, [attempt, attemptId])

  const live = attempt?.status === 'live' || attempt?.status === 'starting'
  useEffect(() => {
    if (attempt && !live) navigate(`/entrenar/intento/${attempt.id}`, { replace: true })
  }, [attempt, live, navigate])

  const fake = Boolean(attempt?.conversation_url?.startsWith('fake:'))
  const finishRef = useRef<() => Promise<void>>(async () => {})
  const call = useTavusCall(live && !fake ? (attempt?.conversation_url ?? null) : null, () => void finishRef.current())
  const [fakeStart] = useState(() => Date.now())
  const elapsed = useElapsed(fake ? fakeStart : call.startedAt)
  const maxSeconds = attempt?.max_seconds ?? 300

  const finish = useCallback(async () => {
    if (finishing.current || !attempt) return
    finishing.current = true
    setEnding(true)
    await call.leave()
    await training.end(attempt.id)
    navigate(`/entrenar/intento/${attempt.id}`, { replace: true })
  }, [attempt, call, navigate])
  finishRef.current = finish

  useEffect(() => {
    if (live && elapsed >= maxSeconds) void finish()
  }, [elapsed, finish, live, maxSeconds])

  useWakeLock(live && !ending)

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') setWasHidden(true)
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [])

  if (loadError)
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-ink px-6 text-center text-white">
        <p className="text-lg font-bold">No pudimos abrir la visita</p>
        <p className="text-white/80">{loadError}</p>
        <Button variant="soft" onClick={() => navigate('/entrenar', { replace: true })}>
          Volver a Entrenar
        </Button>
      </div>
    )

  const photo = faceUrl(attempt?.face_id)
  const waiting = !fake && (call.state === 'joining' || call.state === 'waiting')
  const remaining = Math.max(0, maxSeconds - elapsed)

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-ink text-white">
      {/* El médico ocupa toda la pantalla; el video 16:9 se recorta al centro del rostro. */}
      <div className="absolute inset-0">
        {photo && (
          <img
            src={photo}
            alt=""
            aria-hidden
            className={clsx(
              'h-full w-full object-cover object-[50%_30%] transition-opacity',
              call.doctorVideo && !fake ? 'opacity-0' : waiting ? 'opacity-40' : 'opacity-100',
            )}
          />
        )}
        <video
          ref={call.videoRef}
          autoPlay
          playsInline
          muted
          className={clsx(
            'absolute inset-0 h-full w-full object-cover object-[50%_30%]',
            call.doctorVideo && !fake ? 'opacity-100' : 'opacity-0',
          )}
        />
        <audio ref={call.audioRef} autoPlay />
        <div className="absolute inset-0 bg-gradient-to-b from-black/50 via-transparent to-black/70" aria-hidden />
      </div>

      <header className="relative flex items-start justify-between gap-3 px-5 pt-[calc(14px+var(--safe-top))]">
        <div className="min-w-0">
          <p className="truncate text-lg font-bold">{attempt?.doctor_name ?? 'Médico virtual'}</p>
          <p className="text-sm text-white/80">
            {attempt?.doctor_specialty} · <span className="rounded bg-white/15 px-1.5 py-0.5 text-xs font-semibold">Médico virtual · IA</span>
          </p>
        </div>
        <span
          className={clsx('rounded-full bg-black/40 px-3 py-1 text-base font-semibold tabular-nums', remaining <= 60 && 'text-warn-50')}
          aria-label={`Tiempo de visita ${formatSeconds(elapsed)}`}
        >
          {formatSeconds(elapsed)}
        </span>
      </header>

      <main className="relative flex flex-1 flex-col justify-end gap-3 px-5 pb-4">
        {fake && (
          <p className="mx-auto max-w-[440px] rounded-control bg-white/15 px-4 py-3 text-center text-[15px]">
            Modo de prueba: no hay médico real. Toca «Terminar visita» para ver cómo se evalúa una visita de ejemplo.
          </p>
        )}
        {waiting && <p className="text-center text-base font-semibold">Preparando al médico…</p>}
        {call.state === 'error' && (
          <p role="alert" className="mx-auto max-w-[440px] rounded-control bg-danger-50 px-4 py-3 text-center text-[15px] text-danger">
            {call.error}
          </p>
        )}
        {wasHidden && live && (
          <p className="mx-auto max-w-[440px] rounded-control bg-warn-50 px-4 py-2.5 text-center text-sm text-warn">
            Mantén UNO abierta durante la visita: si cambias de app, el médico puede dejar de escucharte.
          </p>
        )}
        {showCaptions && !fake && <CaptionLine caption={call.caption} />}
        {fake && attempt?.greeting && <CaptionLine caption={{ who: 'doctor', text: attempt.greeting }} />}
      </main>

      <footer className="relative flex items-center justify-center gap-4 px-5 pt-2 pb-[calc(18px+var(--safe-bottom))]">
        {!fake && (
          <>
            <button
              type="button"
              onClick={call.toggleMute}
              aria-pressed={call.muted}
              aria-label={call.muted ? 'Activar micrófono' : 'Silenciar micrófono'}
              className="grid size-14 place-items-center rounded-full bg-white/15 active:bg-white/25"
            >
              {call.muted ? <MicOff size={26} /> : <Mic size={26} />}
            </button>
            <button
              type="button"
              onClick={() => setShowCaptions((v) => !v)}
              aria-pressed={showCaptions}
              aria-label={showCaptions ? 'Ocultar subtítulos' : 'Mostrar subtítulos'}
              className="grid size-14 place-items-center rounded-full bg-white/15 active:bg-white/25"
            >
              <Captions size={26} />
            </button>
          </>
        )}
        <button
          type="button"
          onClick={() => void finish()}
          disabled={ending || !attempt}
          className="flex min-h-14 items-center gap-2 rounded-full bg-danger px-6 text-[17px] font-bold text-white active:opacity-90 disabled:opacity-60"
        >
          <PhoneOff size={22} aria-hidden />
          {ending ? 'Terminando…' : 'Terminar visita'}
        </button>
      </footer>
    </div>
  )
}
