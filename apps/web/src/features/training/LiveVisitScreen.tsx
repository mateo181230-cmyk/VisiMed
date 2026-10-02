import clsx from "clsx";
import {
  Captions,
  Crop,
  Mic,
  MicOff,
  PhoneOff,
  RefreshCw,
  Scan,
  Volume2,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { type PracticeAttempt, training } from "../../api/client";
import { Button } from "../../components/ui";
import { faceUrl, formatSeconds, trainingError } from "./labels";
import { type Caption, useTavusCall, useWakeLock } from "./useTavusCall";

function useElapsed(since: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (since === null) return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [since]);
  return since === null ? 0 : Math.max(0, (now - since) / 1000);
}

function CaptionLine({ caption }: { caption: Caption | null }) {
  if (!caption) return null;
  return (
    <p className="mx-auto max-w-[440px] rounded-control bg-black/55 px-3.5 py-2 text-center text-[15px] leading-snug text-white">
      <span className="font-semibold">
        {caption.who === "doctor" ? "Médico: " : "Tú: "}
      </span>
      {caption.text}
    </p>
  );
}

/**
 * La visita (doc 04 §5.10): el médico a pantalla completa en vertical y dos botones. Sin barra
 * inferior ni nada que distraiga. Termina con «Terminar visita», por tiempo o si el médico cuelga.
 */
export function LiveVisitScreen() {
  const { attemptId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const initial =
    (location.state as { attempt?: PracticeAttempt } | null)?.attempt ?? null;
  const [attempt, setAttempt] = useState<PracticeAttempt | null>(
    initial?.id === attemptId ? initial : null,
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showCaptions, setShowCaptions] = useState(true);
  const [fullFrame, setFullFrame] = useState(false);
  const [ending, setEnding] = useState(false);
  const [wasHidden, setWasHidden] = useState(false);
  const finishing = useRef(false);

  useEffect(() => {
    if (attempt) return;
    void (async () => {
      const res = await training.attempt(attemptId);
      if (res.ok) setAttempt(res.data);
      else setLoadError(trainingError(res));
    })();
  }, [attempt, attemptId]);

  const live = attempt?.status === "live" || attempt?.status === "starting";
  useEffect(() => {
    if (attempt && !live)
      navigate(`/entrenar/intento/${attempt.id}`, { replace: true });
  }, [attempt, live, navigate]);

  const fake = Boolean(attempt?.conversation_url?.startsWith("fake:"));
  const finishRef = useRef<() => Promise<void>>(async () => {});
  const call = useTavusCall(
    live && !fake ? (attempt?.conversation_url ?? null) : null,
    () => void finishRef.current(),
  );
  const [fakeStart] = useState(() => Date.now());
  const elapsed = useElapsed(fake ? fakeStart : call.startedAt);
  const maxSeconds = attempt?.max_seconds ?? 300;

  const finish = useCallback(async () => {
    if (finishing.current || !attempt) return;
    finishing.current = true;
    setEnding(true);
    await call.leave();
    await training.end(attempt.id);
    navigate(`/entrenar/intento/${attempt.id}`, { replace: true });
  }, [attempt, call, navigate]);
  finishRef.current = finish;

  useEffect(() => {
    if (live && elapsed >= maxSeconds) void finish();
  }, [elapsed, finish, live, maxSeconds]);

  useWakeLock(live && !ending);

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "hidden") setWasHidden(true);
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  if (loadError)
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-ink px-6 text-center text-white">
        <p className="text-lg font-bold">No pudimos abrir la visita</p>
        <p className="text-white/80">{loadError}</p>
        <Button
          variant="soft"
          onClick={() => navigate("/entrenar", { replace: true })}
        >
          Volver a Entrenar
        </Button>
      </div>
    );

  const photo = faceUrl(attempt?.face_id);
  const waiting =
    !fake &&
    (call.state === "loading" ||
      call.state === "joining" ||
      call.state === "waiting");
  const remaining = Math.max(0, maxSeconds - elapsed);

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-ink text-white"
      data-call-state={call.state}
    >
      <header className="relative shrink-0 flex items-start justify-between gap-3 px-5 pt-[calc(14px+var(--safe-top))] pb-3">
        <div className="min-w-0">
          <p className="truncate text-lg font-bold">
            {attempt?.doctor_name ?? "Médico virtual"}
          </p>
          <p className="text-sm text-white/80">
            {attempt?.doctor_specialty} ·{" "}
            <span className="inline-block whitespace-nowrap rounded bg-white/15 px-1.5 py-0.5 text-xs font-semibold">
              Médico virtual · IA
            </span>
          </p>
        </div>
        <span
          className={clsx(
            "rounded-full bg-black/40 px-3 py-1 text-base font-semibold tabular-nums",
            remaining <= 60 && "text-warn-50",
          )}
          aria-label={`Tiempo de visita ${formatSeconds(elapsed)}`}
        >
          {formatSeconds(elapsed)}
        </span>
      </header>

      <main className="relative min-h-0 flex flex-1 flex-col justify-end overflow-hidden">
        {/* El recorte conserva la proporción. Limitarlo al espacio entre controles reduce la ampliación. */}
        <div className="absolute inset-0">
          {photo && (
            <img
              src={photo}
              alt=""
              aria-hidden
              className={clsx(
                "h-full w-full transition-opacity",
                fullFrame ? "object-contain" : "object-cover object-[50%_30%]",
                call.doctorVideo && !fake
                  ? "opacity-0"
                  : waiting
                    ? "opacity-40"
                    : "opacity-100",
              )}
            />
          )}
          <video
            ref={call.videoRef}
            autoPlay
            playsInline
            muted
            className={clsx(
              "absolute inset-0 h-full w-full",
              fullFrame ? "object-contain" : "object-cover object-[50%_30%]",
              call.doctorVideo && !fake ? "opacity-100" : "opacity-0",
            )}
          />
          <audio ref={call.audioRef} autoPlay />
        </div>
        {!attempt?.audio_only && (
          <button
            type="button"
            onClick={() => setFullFrame((v) => !v)}
            aria-pressed={fullFrame}
            className="absolute top-3 right-3 z-10 flex min-h-11 items-center gap-2 rounded-full bg-black/55 px-3 text-sm font-semibold active:bg-black/70"
          >
            {fullFrame ? (
              <Crop size={18} aria-hidden />
            ) : (
              <Scan size={18} aria-hidden />
            )}
            {fullFrame ? "Enfocar médico" : "Ver completo"}
          </button>
        )}
        <div className="relative flex max-h-full flex-col gap-3 overflow-y-auto px-5 pb-4 pt-16">
          {fake && (
            <p className="mx-auto max-w-[440px] rounded-control bg-white/15 px-4 py-3 text-center text-[15px]">
              Modo de prueba: no hay médico real. Toca «Terminar visita» para
              ver cómo se evalúa una visita de ejemplo.
            </p>
          )}
          {waiting && !call.needsAudioGesture && (
            <p role="status" className="text-center text-base font-semibold">
              {call.state === "loading"
                ? "Conectando la videollamada…"
                : call.state === "joining"
                  ? "Entrando al consultorio…"
                  : "Esperando voz y video del médico…"}
            </p>
          )}
          {call.needsAudioGesture && (
            <button
              type="button"
              onClick={() => void call.activateAudio()}
              className="mx-auto flex min-h-12 items-center gap-2 rounded-full bg-white px-5 py-3 font-semibold text-ink"
            >
              <Volume2 size={20} aria-hidden /> Activar audio del médico
            </button>
          )}
          {call.state === "error" && (
            <div className="mx-auto max-w-[440px] space-y-3 rounded-control bg-danger-50 px-4 py-3 text-center text-[15px] text-danger">
              <p role="alert">{call.error}</p>
              <button
                type="button"
                onClick={call.reconnect}
                className="inline-flex min-h-11 items-center gap-2 rounded-full bg-white px-4 py-2 font-semibold text-ink"
              >
                <RefreshCw size={18} aria-hidden /> Volver a conectar
              </button>
            </div>
          )}
          {wasHidden && live && (
            <p className="mx-auto max-w-[440px] rounded-control bg-warn-50 px-4 py-2.5 text-center text-sm text-warn">
              Mantén UNO abierta durante la visita: si cambias de app, el médico
              puede dejar de escucharte.
            </p>
          )}
          {showCaptions && !fake && <CaptionLine caption={call.caption} />}
          {fake && attempt?.greeting && (
            <CaptionLine caption={{ who: "doctor", text: attempt.greeting }} />
          )}
        </div>
      </main>

      <footer className="relative shrink-0 flex items-center justify-center gap-3 px-5 pt-3 pb-[calc(18px+var(--safe-bottom))]">
        {!fake && (
          <>
            <button
              type="button"
              onClick={call.toggleMute}
              aria-pressed={call.muted}
              aria-label={
                call.muted ? "Activar micrófono" : "Silenciar micrófono"
              }
              className="grid size-12 shrink-0 place-items-center rounded-full bg-white/15 active:bg-white/25 sm:size-14"
            >
              {call.muted ? <MicOff size={26} /> : <Mic size={26} />}
            </button>
            <button
              type="button"
              onClick={() => setShowCaptions((v) => !v)}
              aria-pressed={showCaptions}
              aria-label={
                showCaptions ? "Ocultar subtítulos" : "Mostrar subtítulos"
              }
              className="grid size-12 shrink-0 place-items-center rounded-full bg-white/15 active:bg-white/25 sm:size-14"
            >
              <Captions size={26} />
            </button>
          </>
        )}
        <button
          type="button"
          onClick={() => void finish()}
          disabled={ending || !attempt}
          className="flex min-h-12 items-center justify-center gap-2 rounded-full bg-danger px-4 text-base font-bold text-white active:opacity-90 disabled:opacity-60 sm:min-h-14"
        >
          <PhoneOff size={22} aria-hidden />
          {ending ? "Terminando…" : "Terminar visita"}
        </button>
      </footer>
    </div>
  );
}
