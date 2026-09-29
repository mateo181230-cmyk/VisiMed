/**
 * Conversación con el médico virtual de Tavus (WebRTC por Daily). ``daily-js`` se descarga solo aquí
 * (import dinámico): no pesa en la carga inicial de UNO ni en el precache del service worker.
 *
 * El celular envía solo su micrófono (cámara apagada, doc 04 D7) y recibe el video y la voz del
 * médico. Los subtítulos salen de los eventos ``conversation.utterance`` de Tavus.
 */
import type { DailyCall } from '@daily-co/daily-js'
import { useCallback, useEffect, useRef, useState } from 'react'

export type CallState = 'joining' | 'waiting' | 'live' | 'ended' | 'error'

export interface Caption {
  who: 'doctor' | 'rep'
  text: string
}

// Daily no admite dos instancias a la vez: se espera a que termine de destruirse la anterior
// (React en modo estricto monta, desmonta y vuelve a montar en desarrollo).
let pendingDestroy: Promise<void> | null = null

export function useTavusCall(url: string | null, onRemoteLeft: () => void) {
  const [state, setState] = useState<CallState>('joining')
  const [error, setError] = useState<string | null>(null)
  const [muted, setMuted] = useState(false)
  const [caption, setCaption] = useState<Caption | null>(null)
  const [doctorVideo, setDoctorVideo] = useState(false)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const callRef = useRef<DailyCall | null>(null)
  const leftRef = useRef(onRemoteLeft)
  leftRef.current = onRemoteLeft

  useEffect(() => {
    if (!url) return
    let cancelled = false
    let call: DailyCall | null = null

    ;(async () => {
      if (pendingDestroy) await pendingDestroy
      const { default: Daily } = await import('@daily-co/daily-js')
      if (cancelled) return
      call = Daily.createCallObject({ subscribeToTracksAutomatically: true, audioSource: true, videoSource: false })
      callRef.current = call

      const markLive = () => {
        setState('live')
        setStartedAt((t) => t ?? Date.now())
      }
      call.on('joined-meeting', () => setState((s) => (s === 'joining' ? 'waiting' : s)))
      call.on('track-started', (ev) => {
        if (!ev?.participant || ev.participant.local) return
        const track = ev.track
        if (track.kind === 'video' && videoRef.current) {
          videoRef.current.srcObject = new MediaStream([track])
          void videoRef.current.play().catch(() => {})
          setDoctorVideo(true)
        }
        if (track.kind === 'audio' && audioRef.current) {
          audioRef.current.srcObject = new MediaStream([track])
          void audioRef.current.play().catch(() => {})
        }
        markLive()
      })
      call.on('participant-left', (ev) => {
        if (ev?.participant && !ev.participant.local) leftRef.current()
      })
      call.on('app-message', (ev) => {
        const data = (ev?.data ?? {}) as { event_type?: string; properties?: { role?: string; speech?: string } }
        if (data.event_type !== 'conversation.utterance') return
        const text = data.properties?.speech?.trim()
        if (text) setCaption({ who: data.properties?.role === 'user' ? 'rep' : 'doctor', text })
      })
      call.on('camera-error', () => {
        setError('No pudimos usar tu micrófono. Revisa el permiso del navegador e inténtalo de nuevo.')
        setState('error')
      })
      call.on('error', (ev) => {
        setError(ev?.errorMsg ? `Se perdió la conexión con el médico (${ev.errorMsg}).` : 'Se perdió la conexión con el médico.')
        setState('error')
      })
      call.on('left-meeting', () => setState((s) => (s === 'error' ? s : 'ended')))
      try {
        await call.join({ url, startVideoOff: true, startAudioOff: false })
      } catch (e) {
        if (cancelled) return
        setError(
          `No pudimos conectar con el médico. ${e instanceof Error ? e.message : ''} Si estás en una red de oficina, prueba con los datos del celular.`.trim(),
        )
        setState('error')
      }
    })()

    return () => {
      cancelled = true
      const current = call
      callRef.current = null
      if (current) {
        pendingDestroy = (async () => {
          try {
            await current.leave()
          } catch {
            /* ya salió */
          }
          await current.destroy()
        })().finally(() => {
          pendingDestroy = null
        })
      }
    }
  }, [url])

  const toggleMute = useCallback(() => {
    const call = callRef.current
    if (!call) return
    const next = !muted
    call.setLocalAudio(!next)
    setMuted(next)
  }, [muted])

  const leave = useCallback(async () => {
    const call = callRef.current
    if (!call) return
    try {
      await call.leave()
    } catch {
      /* ya salió */
    }
  }, [])

  return { state, error, muted, toggleMute, leave, caption, doctorVideo, startedAt, videoRef, audioRef }
}

/** Mantiene la pantalla encendida mientras dure la visita (si el navegador lo permite). */
export function useWakeLock(active: boolean): void {
  useEffect(() => {
    if (!active || !('wakeLock' in navigator)) return
    let sentinel: WakeLockSentinel | null = null
    let released = false
    const acquire = async () => {
      try {
        sentinel = await navigator.wakeLock.request('screen')
      } catch {
        /* sin permiso o sin soporte: no es grave */
      }
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible' && !released) void acquire()
    }
    void acquire()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      released = true
      document.removeEventListener('visibilitychange', onVisible)
      void sentinel?.release().catch(() => {})
    }
  }, [active])
}
