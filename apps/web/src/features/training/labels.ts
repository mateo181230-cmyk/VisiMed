/** Textos y utilidades del módulo Entrenar. Lenguaje de capacitación, sin elementos de juego (doc 04 §6). */
import type { DoctorAvailability, TrainingScenarioSummary } from '../../api/client'

export type Tone = 'brand' | 'ok' | 'warn' | 'muted'

export const TONE_CLASS: Record<Tone, string> = {
  brand: 'bg-brand-50 text-brand',
  ok: 'bg-ok-50 text-ok',
  warn: 'bg-warn-50 text-warn',
  muted: 'bg-line/70 text-muted',
}

export function progressPill(status: TrainingScenarioSummary['progress']['status']): { text: string; tone: Tone } {
  switch (status) {
    case 'aprobado':
      return { text: 'Aprobado', tone: 'ok' }
    case 'practicado':
      return { text: 'Practicado', tone: 'brand' }
    default:
      return { text: 'Sin practicar', tone: 'muted' }
  }
}

export const BAND_TONE: Record<string, Tone> = {
  sobresaliente: 'ok',
  bueno: 'brand',
  intermedio: 'warn',
  deficiente: 'warn',
}

/** Foto del médico: cuadro de su cara en Tavus (servido por la propia app). */
export function faceUrl(faceId: string | null | undefined): string | null {
  return faceId ? `/entrenar/${faceId}.jpg` : null
}

/** ¿Se puede empezar una visita ahora? Si no, qué decirle al visitador. */
export function doctorNotice(doctor: DoctorAvailability): { canStart: boolean; tone: 'info' | 'warn'; text: string } | null {
  if (doctor.status === 'off') return { canStart: false, tone: 'info', text: doctor.message ?? '' }
  if (doctor.status === 'unavailable') return { canStart: false, tone: 'warn', text: doctor.message ?? '' }
  if (doctor.mode === 'fake')
    return {
      canStart: true,
      tone: 'info',
      text: 'Modo de prueba: la visita usa un médico simulado, sin video. Sirve para ver cómo se evalúa.',
    }
  return null
}

/** Mensaje en español para un error de la API del módulo. */
export function trainingError(result: { kind: string; code?: string; message?: string }): string {
  if (result.kind === 'network') return 'Necesitas conexión para entrenar. Revisa tu señal e inténtalo de nuevo.'
  if (result.message) return result.message
  return 'Algo falló. Inténtalo de nuevo en un momento.'
}

export function formatSeconds(total: number): string {
  const s = Math.max(0, Math.floor(total))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

export function formatDateTime(iso: string, tz: string): string {
  return new Intl.DateTimeFormat('es-CO', {
    timeZone: tz,
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(iso))
}
