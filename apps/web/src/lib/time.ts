/**
 * Fechas y horas en la zona horaria del negocio (por defecto America/Bogota).
 *
 * Todo se guarda y se envía en UTC (ISO 8601 con «Z»); estas funciones convierten desde y hacia el
 * día y la hora *locales* de la agenda sin depender de la zona del teléfono.
 */

export const DEFAULT_TZ = 'America/Bogota'

const pad = (n: number): string => String(n).padStart(2, '0')

interface Parts {
  y: number
  m: number
  d: number
  h: number
  mi: number
  s: number
}

const formatters = new Map<string, Intl.DateTimeFormat>()
function formatter(tz: string): Intl.DateTimeFormat {
  let f = formatters.get(tz)
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
    formatters.set(tz, f)
  }
  return f
}

function partsIn(date: Date, tz: string): Parts {
  const out: Record<string, number> = {}
  for (const p of formatter(tz).formatToParts(date)) {
    if (p.type !== 'literal') out[p.type] = Number(p.value)
  }
  return { y: out.year!, m: out.month!, d: out.day!, h: out.hour! % 24, mi: out.minute!, s: out.second! }
}

/** Desfase de la zona respecto de UTC, en minutos, en el instante dado (Bogotá: −300). */
export function tzOffsetMinutes(at: Date, tz: string): number {
  const p = partsIn(at, tz)
  const asUtc = Date.UTC(p.y, p.m - 1, p.d, p.h, p.mi, p.s)
  return Math.round((asUtc - Math.floor(at.getTime() / 1000) * 1000) / 60000)
}

/** ``YYYY-MM-DD`` del día local que contiene el instante. */
export function dateKey(at: Date | string, tz: string): string {
  const p = partsIn(typeof at === 'string' ? new Date(at) : at, tz)
  return `${p.y}-${pad(p.m)}-${pad(p.d)}`
}

export function todayKey(tz: string, now: Date = new Date()): string {
  return dateKey(now, tz)
}

function keyToUtcDate(key: string): Date {
  const [y, m, d] = key.split('-').map(Number)
  return new Date(Date.UTC(y!, m! - 1, d!))
}

export function addDays(key: string, n: number): string {
  const d = keyToUtcDate(key)
  d.setUTCDate(d.getUTCDate() + n)
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`
}

/** Lunes de la semana que contiene el día. */
export function weekStart(key: string): string {
  const dow = keyToUtcDate(key).getUTCDay() // 0 = domingo
  return addDays(key, -((dow + 6) % 7))
}

/** Convierte una hora de pared local (``HH:MM``) de un día local a un instante UTC. */
export function localToUtc(key: string, hhmm: string, tz: string): Date {
  const [y, m, d] = key.split('-').map(Number)
  const [h, mi] = hhmm.split(':').map(Number)
  const guess = Date.UTC(y!, m! - 1, d!, h!, mi!)
  const off1 = tzOffsetMinutes(new Date(guess), tz)
  let t = guess - off1 * 60000
  const off2 = tzOffsetMinutes(new Date(t), tz)
  if (off2 !== off1) t = guess - off2 * 60000
  return new Date(t)
}

/** ``HH:MM`` (24 h) local del instante. */
export function hhmm(at: Date | string, tz: string): string {
  const p = partsIn(typeof at === 'string' ? new Date(at) : at, tz)
  return `${pad(p.h)}:${pad(p.mi)}`
}

/** ``"14:30"`` → ``2:30 PM`` (para etiquetas de horas sugeridas). */
export function format12(hhmmValue: string): string {
  const [h, m] = hhmmValue.split(':').map(Number)
  const h12 = h! % 12 === 0 ? 12 : h! % 12
  return `${h12}:${pad(m!)} ${h! < 12 ? 'AM' : 'PM'}`
}

/** ``10:30 AM`` */
export function formatTime(at: Date | string, tz: string): string {
  const p = partsIn(typeof at === 'string' ? new Date(at) : at, tz)
  const h12 = p.h % 12 === 0 ? 12 : p.h % 12
  return `${h12}:${pad(p.mi)} ${p.h < 12 ? 'AM' : 'PM'}`
}

const DAYS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado']
const MONTHS = [
  'enero',
  'febrero',
  'marzo',
  'abril',
  'mayo',
  'junio',
  'julio',
  'agosto',
  'septiembre',
  'octubre',
  'noviembre',
  'diciembre',
]
const cap = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1)

/** ``Martes, 22 de abril`` */
export function formatLongDate(key: string): string {
  const d = keyToUtcDate(key)
  return `${cap(DAYS[d.getUTCDay()]!)}, ${d.getUTCDate()} de ${MONTHS[d.getUTCMonth()]}`
}

/** ``Miércoles 23`` */
export function formatDayTitle(key: string): string {
  const d = keyToUtcDate(key)
  return `${cap(DAYS[d.getUTCDay()]!)} ${d.getUTCDate()}`
}

/** Letra del día para la tira semanal: L M M J V S D */
export function dayLetter(key: string): string {
  return ['D', 'L', 'M', 'M', 'J', 'V', 'S'][keyToUtcDate(key).getUTCDay()]!
}

export function dayNumber(key: string): number {
  return keyToUtcDate(key).getUTCDate()
}

export function monthName(key: string): string {
  return MONTHS[keyToUtcDate(key).getUTCMonth()]!
}

/** Horas sugeridas cada 30 min. Hoy arranca en la próxima media hora; otros días a las 8:00. */
export function suggestedSlots(key: string, tz: string, now: Date = new Date(), count = 8): string[] {
  let startMinutes = 8 * 60
  if (key === todayKey(tz, now)) {
    const [h, m] = hhmm(now, tz).split(':').map(Number)
    startMinutes = Math.ceil((h! * 60 + m! + 1) / 30) * 30
    startMinutes = Math.max(startMinutes, 7 * 60)
  }
  const slots: string[] = []
  for (let t = startMinutes; slots.length < count && t < 24 * 60; t += 30) {
    slots.push(`${pad(Math.floor(t / 60))}:${pad(t % 60)}`)
  }
  return slots
}
