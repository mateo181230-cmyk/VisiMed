import { type OutboxStatus, type UnoDB, db } from '../db/db'
import { newId } from '../lib/ids'
import type { EventSpec } from './events'

/**
 * Guarda un evento en la cola local. Es la **única** forma de que el visitador cambie algo:
 * responde en milisegundos y no depende de la red (doc 01 §3, principio 1).
 */
export async function enqueue(
  spec: EventSpec,
  database: UnoDB = db,
  status: OutboxStatus = 'pending',
): Promise<string> {
  const eventId = newId()
  await database.outbox.add({
    event_id: eventId,
    type: spec.type,
    visit_id: spec.visitId,
    device_ts: new Date().toISOString(),
    payload: spec.payload as unknown as Record<string, unknown>,
    status,
    attempts: 0,
    created_at: new Date().toISOString(),
  })
  notifyOutboxChanged()
  return eventId
}

/** Toques (Llegué / Terminé) cuya ubicación se está tomando ahora mismo en esta pestaña. */
const capturing = new Set<string>()

/**
 * Registra el toque al instante, con su hora, y lo deja en `capturing`: el motor de sincronización no lo
 * envía hasta que se le adjunte la ubicación (`completeCapture`). La pantalla ya lo muestra (doc 01 §9.2).
 */
export async function enqueueCapturing(spec: EventSpec, database: UnoDB = db): Promise<string> {
  const eventId = await enqueue(spec, database, 'capturing')
  capturing.add(eventId)
  return eventId
}

/** Adjunta la ubicación al toque y lo pasa a `pending`. Si el toque ya no está en `capturing`, no hace nada. */
export async function completeCapture(
  eventId: string,
  extra: Record<string, unknown>,
  database: UnoDB = db,
): Promise<void> {
  try {
    await database.outbox
      .where('event_id')
      .equals(eventId)
      .filter((e) => e.status === 'capturing')
      .modify((e) => {
        e.payload = { ...e.payload, ...extra }
        e.status = 'pending'
      })
  } finally {
    capturing.delete(eventId)
  }
  notifyOutboxChanged()
}

/**
 * Si la app se cerró en medio de una captura, el toque queda sin ubicación pero NO se pierde: pasa a
 * `pending` con `location = null` (doc 01 §9.2). Se llama al arrancar el motor; se salta lo que esta misma
 * pestaña aún está capturando.
 */
export async function recoverCapturing(database: UnoDB = db): Promise<number> {
  const n = await database.outbox
    .where('status')
    .equals('capturing')
    .filter((e) => !capturing.has(e.event_id))
    .modify((e) => {
      e.payload = { ...e.payload, location: null, error: 'interrupted' }
      e.status = 'pending'
    })
  if (n > 0) notifyOutboxChanged()
  return n
}

type Listener = () => void
const listeners = new Set<Listener>()

/** El motor de sincronización se suscribe aquí para enviar apenas hay algo nuevo. */
export function onOutboxChanged(fn: Listener): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function notifyOutboxChanged(): void {
  for (const fn of listeners) fn()
}

/** Reintento manual («Reintentar» en Pendientes): los vencidos vuelven a la cola. */
export async function retryExpired(database: UnoDB = db): Promise<number> {
  const n = await database.outbox.where('status').equals('expired').modify({ status: 'pending' })
  if (n > 0) notifyOutboxChanged()
  return n
}
