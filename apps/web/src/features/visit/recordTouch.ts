/**
 * Llegué / Terminé: un toque, una ubicación (doc 01 §8.1, §9.2; decisión del cliente del 28 sep 2026).
 *
 *  1. El toque se guarda YA en la cola local, con su hora, y la pantalla lo muestra al instante.
 *  2. Se toma UNA lectura de ubicación (`capturarUbicacion`).
 *  3. La lectura se adjunta al mismo evento y este pasa a `pending` para enviarse.
 *
 * Todo esto vive fuera de los componentes: si el visitador cambia de pantalla o cierra la app a medias,
 * el toque no se pierde (al reabrir, `recoverCapturing` lo envía sin ubicación).
 */
import { type UnoDB, db } from '../../db/db'
import { capturarUbicacion } from '../geo/capturar'
import type { Ubicacion } from '../geo/tipos'
import {
  type TouchMoment,
  type VisitTouchPayload,
  type WireLocation,
  visitArrived,
  visitFinished,
  visitLocationRetried,
} from '../../sync/events'
import { completeCapture, enqueue, enqueueCapturing } from '../../sync/outbox'

/** Ventana para volver a tomar la ubicación de un toque (contrato `visit_location_retried`). */
export const RETRY_WINDOW_MS = 2 * 60_000

export interface TouchDeps {
  database?: UnoDB
  capturar?: () => Promise<Ubicacion>
}

/** La ubicación de la app → la forma exacta que valida el servidor. */
export function toWireLocation(u: Ubicacion): WireLocation | null {
  if (u.lat === null || u.lng === null || u.precision_m === null || u.fix_ts === null) return null
  return {
    lat: u.lat,
    lng: u.lng,
    precision_m: u.precision_m,
    fix_ts: u.fix_ts,
    source: u.fuente === 'reutilizada' ? 'reused' : 'gps',
  }
}

function diagnostics(u: Ubicacion): Pick<VisitTouchPayload, 'permission' | 'duration_ms' | 'error'> {
  return { permission: u.permiso, duration_ms: u.duracion_ms, error: u.error }
}

const NO_LOCATION: Ubicacion = {
  lat: null,
  lng: null,
  precision_m: null,
  fix_ts: null,
  fuente: 'ninguna',
  permiso: 'prompt',
  duracion_ms: 0,
  error: 'no_disponible',
}

async function read(capturar: () => Promise<Ubicacion>): Promise<Ubicacion> {
  try {
    return await capturar()
  } catch {
    // `capturarUbicacion` no lanza; esto protege el toque si otra implementación sí lo hiciera.
    return NO_LOCATION
  }
}

/** Toques en curso por visita y momento: un segundo toque rápido reutiliza el primero en vez de duplicarlo. */
const inFlight = new Map<string, Promise<Ubicacion>>()

/** Registra «Llegué» o «Terminé». Devuelve la ubicación cuando llega; el toque ya existía desde el primer instante. */
export function recordTouch(
  moment: TouchMoment,
  visitId: string,
  { database = db, capturar = capturarUbicacion }: TouchDeps = {},
): Promise<Ubicacion> {
  const key = `${moment}:${visitId}`
  const running = inFlight.get(key)
  if (running) return running
  const task = (async () => {
    const spec =
      moment === 'arrival' ? visitArrived(visitId, { location: null }) : visitFinished(visitId, { location: null })
    const eventId = await enqueueCapturing(spec, database)
    const u = await read(capturar)
    await completeCapture(eventId, { location: toWireLocation(u), ...diagnostics(u) }, database)
    return u
  })().finally(() => inFlight.delete(key))
  inFlight.set(key, task)
  return task
}

/**
 * «Reintentar ubicación»: vuelve a tomar la lectura de un toque que quedó sin ubicación o imprecisa.
 * Solo se envía si la nueva lectura existe; si falla otra vez, el toque queda como estaba.
 */
export async function retryLocation(
  moment: TouchMoment,
  visitId: string,
  { database = db, capturar = capturarUbicacion }: TouchDeps = {},
): Promise<Ubicacion> {
  const u = await read(capturar)
  const location = toWireLocation(u)
  if (location) {
    await enqueue(
      visitLocationRetried(visitId, { moment, location, permission: u.permiso, duration_ms: u.duracion_ms }),
      database,
    )
  }
  return u
}
