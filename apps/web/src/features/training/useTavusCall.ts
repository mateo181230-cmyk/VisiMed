/**
 * Conversación con el médico virtual de Tavus (WebRTC por Daily). El escenario precarga el cliente
 * antes de abrir la sesión; la visita reutiliza esa instancia para conectarse enseguida.
 *
 * El celular envía solo su micrófono (cámara apagada, doc 04 D7) y recibe el video y la voz del
 * médico. Los subtítulos salen de los eventos ``conversation.utterance`` de Tavus.
 */
import type { DailyCall, DailyParticipant } from '@daily-co/daily-js'
import { useCallback, useEffect, useRef, useState } from 'react'
import { acquireDailyCall, releaseDailyCall } from './dailyClient'

export type CallState = 'loading' | 'joining' | 'waiting' | 'live' | 'ended' | 'error'

export interface Caption {
  who: 'doctor' | 'rep'
  text: string
}

const CONNECT_TIMEOUT_MS = 30_000

export function useTavusCall(url: string | null, onRemoteLeft: () => void) {
  const [state, setState] = useState<CallState>('loading')
  const [error, setError] = useState<string | null>(null)
  const [muted, setMuted] = useState(false)
  const [caption, setCaption] = useState<Caption | null>(null)
  const [doctorVideo, setDoctorVideo] = useState(false)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [needsAudioGesture, setNeedsAudioGesture] = useState(false)
  const [restart, setRestart] = useState(0)
  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const callRef = useRef<DailyCall | null>(null)
  const leftRef = useRef(onRemoteLeft)
  const leavingRef = useRef(false)
  leftRef.current = onRemoteLeft

  useEffect(() => {
    if (!url) return
    let cancelled = false
    let failed = false
    let released = false
    let call: DailyCall | null = null
    leavingRef.current = false
    setState('loading')
    setError(null)
    setDoctorVideo(false)
    setNeedsAudioGesture(false)
    setMuted(false)
    setCaption(null)

    const destroy = () => {
      if (!call || released) return
      released = true
      if (callRef.current === call) callRef.current = null
      void releaseDailyCall(call)
    }
    const fail = (message: string) => {
      if (cancelled || failed) return
      failed = true
      clearTimeout(deadline)
      setError(message)
      setState('error')
      destroy()
    }
    const deadline = setTimeout(() => {
      fail('El teléfono no logró conectar con el médico. Vuelve a conectar; si continúa, prueba otra red.')
    }, CONNECT_TIMEOUT_MS)

    const markLive = () => {
      if (cancelled || failed) return
      clearTimeout(deadline)
      setState('live')
      setStartedAt((t) => t ?? Date.now())
    }
    const video = videoRef.current
    const audio = audioRef.current
    const videoPlaying = () => {
      if (cancelled || failed) return
      setDoctorVideo(true)
      markLive()
    }
    video?.addEventListener('playing', videoPlaying)

    const attachTrack = (track: MediaStreamTrack) => {
      if (cancelled || failed) return
      const element = track.kind === 'video' ? video : track.kind === 'audio' ? audio : null
      if (!element || (element.srcObject as MediaStream | null)?.getTracks().includes(track)) return
      element.srcObject = new MediaStream([track])
      void element.play().then(() => {
        if (track.kind === 'audio') {
          if (cancelled || failed) return
          setNeedsAudioGesture(false)
          markLive()
        }
      }).catch((error: unknown) => {
        if (cancelled || failed || track.kind !== 'audio') return
        if ((error as DOMException)?.name === 'NotAllowedError') {
          // Safari puede exigir otro toque tras el POST. No se oculta el bloqueo del audio.
          clearTimeout(deadline)
          setNeedsAudioGesture(true)
        }
      })
    }
    const syncParticipant = (participant: DailyParticipant) => {
      if (participant.local) return
      for (const kind of ['video', 'audio'] as const) {
        const media = participant.tracks[kind]
        if (media.state === 'playable' && media.persistentTrack) attachTrack(media.persistentTrack)
      }
    }
    const syncTracks = () => {
      if (call && !cancelled && !failed) Object.values(call.participants()).forEach(syncParticipant)
    }

    ;(async () => {
      try {
        call = await acquireDailyCall(() => cancelled || failed)
        if (!call) return
        if (cancelled || failed) {
          destroy()
          return
        }
        callRef.current = call
        setState('joining')
        call.on('joined-meeting', () => {
          if (cancelled || failed) return
          setState((s) => s === 'joining' ? 'waiting' : s)
          syncTracks()
        })
        call.on('participant-joined', (ev) => { if (ev?.participant) syncParticipant(ev.participant) })
        call.on('participant-updated', (ev) => { if (ev?.participant) syncParticipant(ev.participant) })
        call.on('track-started', (ev) => {
          if (ev?.participant && !ev.participant.local) attachTrack(ev.track)
        })
        call.on('track-stopped', (ev) => {
          if (!cancelled && !failed && ev?.track.kind === 'video' && !ev.participant?.local) setDoctorVideo(false)
        })
        call.on('participant-left', (ev) => {
          if (!cancelled && !failed && !leavingRef.current && ev?.participant && !ev.participant.local) leftRef.current()
        })
        call.on('app-message', (ev) => {
          if (cancelled || failed) return
          const data = (ev?.data ?? {}) as { event_type?: string; properties?: { role?: string; speech?: string } }
          if (data.event_type !== 'conversation.utterance') return
          const text = data.properties?.speech?.trim()
          if (text) setCaption({ who: data.properties?.role === 'user' ? 'rep' : 'doctor', text })
        })
        call.on('camera-error', () => fail('No pudimos usar tu micrófono. Revisa el permiso del navegador y vuelve a conectar.'))
        call.on('error', () => fail('Se perdió la conexión con el médico. Vuelve a conectar.'))
        call.on('left-meeting', () => {
          if (!cancelled && !failed) setState('ended')
        })
        await call.join({ url, audioSource: true, videoSource: false, startVideoOff: true, startAudioOff: false })
        syncTracks()
      } catch (e) {
        fail(e instanceof Error ? e.message : 'No pudimos conectar con el médico. Revisa tu conexión y vuelve a conectar.')
      }
    })()

    return () => {
      cancelled = true
      clearTimeout(deadline)
      video?.removeEventListener('playing', videoPlaying)
      if (video) video.srcObject = null
      if (audio) audio.srcObject = null
      destroy()
    }
  }, [url, restart])

  const activateAudio = useCallback(async () => {
    if (!callRef.current || !audioRef.current?.srcObject) return
    try {
      await audioRef.current?.play()
      setNeedsAudioGesture(false)
      setState('live')
      setStartedAt((t) => t ?? Date.now())
    } catch {
      setNeedsAudioGesture(true)
    }
  }, [])

  const reconnect = useCallback(() => setRestart((n) => n + 1), [])

  const toggleMute = useCallback(() => {
    const call = callRef.current
    if (!call) return
    const next = !muted
    call.setLocalAudio(!next)
    setMuted(next)
  }, [muted])

  const leave = useCallback(async () => {
    leavingRef.current = true
    const call = callRef.current
    if (!call) return
    try {
      await call.leave()
    } catch {
      /* ya salió */
    }
  }, [])

  return { state, error, muted, toggleMute, leave, reconnect, activateAudio, needsAudioGesture, caption, doctorVideo, startedAt, videoRef, audioRef }
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
