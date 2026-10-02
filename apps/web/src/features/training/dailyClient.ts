import type { DailyCall } from '@daily-co/daily-js'

const LOAD_TIMEOUT_MS = 15_000
const PREPARED_TTL_MS = 60_000
let clientModule: Promise<typeof import('@daily-co/daily-js')> | null = null
let prepared: Promise<DailyCall> | null = null
let preparedCall: DailyCall | null = null
let preparationToken: object | null = null
let expiry: ReturnType<typeof setTimeout> | null = null
let pendingDestroy: Promise<void> = Promise.resolve()

/** Descarga el cliente al abrir el escenario; no abre salas ni pide dispositivos. */
export function preloadDailyClient() {
  clientModule ??= import('@daily-co/daily-js').catch((error: unknown) => {
    clientModule = null
    throw error
  })
  return clientModule
}

/** Daily solo admite una instancia: destruirla también abandona la sala. */
export function releaseDailyCall(call: DailyCall): Promise<void> {
  const destroy = pendingDestroy.then(() => call.destroy()).catch(() => {})
  pendingDestroy = destroy
  return destroy
}

export async function discardPreparedCall(): Promise<void> {
  if (expiry) clearTimeout(expiry)
  expiry = null
  const call = preparedCall
  prepared = null
  preparedCall = null
  preparationToken = null
  if (call) await releaseDailyCall(call)
}

/** Carga también el motor WebRTC ANTES de crear una conversación de pago. */
export function prepareDailyCall(): Promise<DailyCall> {
  if (prepared) return prepared
  const token = {}
  preparationToken = token
  const loading = (async () => {
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      const ready = (async () => {
        await pendingDestroy
        const { default: Daily } = await preloadDailyClient()
        if (preparationToken !== token) throw new Error('Preparación cancelada')
        const call = Daily.createCallObject({
          subscribeToTracksAutomatically: true,
          audioSource: false,
          videoSource: false,
        })
        preparedCall = call
        await call.load()
        return call
      })()
      const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('Tiempo de carga agotado')), LOAD_TIMEOUT_MS)
      })
      const call = await Promise.race([ready, timeout])
      // Si se abandona el escenario durante el POST, no queda un cliente huérfano.
      expiry = setTimeout(() => void discardPreparedCall(), PREPARED_TTL_MS)
      return call
    } catch {
      if (preparationToken === token) await discardPreparedCall()
      throw new Error('No pudimos cargar la videollamada. Revisa tu conexión y vuelve a intentarlo.')
    } finally {
      if (timer) clearTimeout(timer)
    }
  })()
  prepared = loading
  return loading
}

/** La pantalla de la visita recibe el mismo cliente ya cargado en el escenario. */
export async function acquireDailyCall(isCancelled: () => boolean): Promise<DailyCall | null> {
  const call = await prepareDailyCall()
  if (isCancelled()) return null
  if (expiry) clearTimeout(expiry)
  expiry = null
  prepared = null
  preparedCall = null
  preparationToken = null
  return call
}
