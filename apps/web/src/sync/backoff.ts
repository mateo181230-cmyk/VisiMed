/**
 * Reintentos de la cola (doc 01 §10.3): 1, 2, 4, 8 min y luego cada 8 min, con ±20 % de variación
 * aleatoria, hasta 24 h. Pasado ese plazo el evento queda «vencido» y se reintenta con un toque.
 */
export const BACKOFF_STEPS_MS = [60_000, 120_000, 240_000, 480_000]
export const EXPIRY_MS = 24 * 60 * 60 * 1000

/** ``attempt`` empieza en 1 (el primer fallo). */
export function backoffDelayMs(attempt: number, random: () => number = Math.random): number {
  const base = BACKOFF_STEPS_MS[Math.min(Math.max(attempt, 1), BACKOFF_STEPS_MS.length) - 1]!
  const jitter = 1 + (random() * 0.4 - 0.2)
  return Math.round(base * jitter)
}

export function isExpired(createdAtIso: string, now: number = Date.now()): boolean {
  return now - new Date(createdAtIso).getTime() > EXPIRY_MS
}
