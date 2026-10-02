/**
 * Cliente de la API, tipado desde el contrato OpenAPI del servidor (``openapi-typescript``).
 *
 * - Adjunta el token de acceso y, si el servidor responde 401, intenta **una** vez refrescarlo con
 *   la cookie ``httpOnly`` (una sola petición de refresco a la vez) y repite la llamada.
 * - Nunca lanza por problemas de red: devuelve un resultado con ``kind`` para que la interfaz
 *   decida (sin red no es un error, es un estado; doc 01 §3, principio 3).
 */
import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type StateOut = components['schemas']['StateOut']
export type SyncOut = components['schemas']['SyncOut']
export type SessionOut = components['schemas']['SessionOut']
export type UserOut = components['schemas']['UserOut']
export type Preferences = components['schemas']['PreferencesOut']
export type PilotSnapshot = components['schemas']['PilotSnapshot']

export type ApiFailure =
  | { ok: false; kind: 'network' }
  | { ok: false; kind: 'auth'; status: 401 }
  | {
      ok: false
      kind: 'server'
      status: number
      code?: string
      message?: string
    }
  | {
      ok: false
      kind: 'client'
      status: number
      code?: string
      message?: string
      /** El backend identificó un error del evento, no del transporte ni de la sesión. */
      eventValidation?: true
    }
export type ApiResult<T> = { ok: true; data: T } | ApiFailure

const client = createClient<paths>({ baseUrl: '' })

let accessToken: string | null = null
let onRefreshed: ((s: SessionOut) => void) | null = null
let onAuthLost: (() => void) | null = null
let refreshing: Promise<boolean> | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function configureAuthHandlers(handlers: {
  onRefreshed: (session: SessionOut) => void
  onAuthLost: () => void
}): void {
  onRefreshed = handlers.onRefreshed
  onAuthLost = handlers.onAuthLost
}

function bearer(): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {}
}

export const intelligenceApi = {
  snapshot: (): Promise<ApiResult<PilotSnapshot>> =>
    call(() => client.GET('/v1/intelligence/snapshot', { headers: bearer() })),
}

interface Raw<T> {
  data?: T
  error?: unknown
  response: Response
}

function detailOf(error: unknown): { code?: string; message?: string } {
  const detail = (error as { detail?: unknown } | undefined)?.detail
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const d = detail as { code?: unknown; message?: unknown }
    return {
      code: typeof d.code === 'string' ? d.code : undefined,
      message: typeof d.message === 'string' ? d.message : undefined,
    }
  }
  return {}
}

function isEventValidation(status: number, error: unknown, code?: string): boolean {
  if (status !== 400 && status !== 422) return false
  if (code === 'invalid_payload' || code === 'invalid_event_envelope') return true
  // FastAPI valida el sobre antes de procesar el lote. Solo se aísla un evento si
  // todos los errores apuntan a uno: un device_id/sent_at inválido no invalida visitas.
  const detail = (error as { detail?: unknown } | undefined)?.detail
  return status === 422 && Array.isArray(detail) && detail.length > 0 && detail.every((item: unknown) => {
    if (!item || typeof item !== 'object') return false
    const { loc, type, msg } = item as { loc?: unknown; type?: unknown; msg?: unknown }
    return Array.isArray(loc) && loc.length >= 3 && loc[0] === 'body' && loc[1] === 'events'
      && Number.isInteger(loc[2]) && loc[2] >= 0 && typeof type === 'string' && typeof msg === 'string'
  })
}

async function attempt<T>(fn: () => Promise<Raw<T>>): Promise<Raw<T> | null> {
  try {
    return await fn()
  } catch {
    return null // fetch lanza TypeError sin red
  }
}

function classify<T>(res: Raw<T>): ApiResult<T> {
  const { status } = res.response
  if (res.response.ok) return { ok: true, data: res.data as T }
  if (status === 401) return { ok: false, kind: 'auth', status: 401 }
  const d = detailOf(res.error)
  const eventValidation = isEventValidation(status, res.error, d.code)
  return status >= 500 || status === 429
    ? { ok: false, kind: 'server', status, ...d }
    : { ok: false, kind: 'client', status, ...d,
        ...(eventValidation ? { eventValidation: true as const, code: d.code ?? 'invalid_event_envelope' } : {}),
      }
}

/** Llama al servidor con reintento de sesión. ``refresh: false`` para el ingreso y el refresco. */
async function call<T>(fn: () => Promise<Raw<T>>, refresh = true): Promise<ApiResult<T>> {
  let res = await attempt(fn)
  if (res === null) return { ok: false, kind: 'network' }
  if (res.response.status === 401 && refresh) {
    const ok = await refreshSession()
    if (!ok) return { ok: false, kind: 'auth', status: 401 }
    res = await attempt(fn)
    if (res === null) return { ok: false, kind: 'network' }
  }
  return classify(res)
}

/** Refresca el token de acceso con la cookie de refresco. Una sola petición a la vez. */
export function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      const res = await attempt(() => client.POST('/v1/auth/refresh'))
      if (res === null) return false // sin red: no se pierde la sesión, solo no se refresca
      if (res.response.ok && res.data) {
        accessToken = res.data.access_token
        onRefreshed?.(res.data)
        return true
      }
      if (res.response.status === 401) {
        accessToken = null
        onAuthLost?.()
      }
      return false
    })().finally(() => {
      refreshing = null
    })
  }
  return refreshing
}

// ------------------------------------------------------------------ sesión

export function login(phone: string, pin: string): Promise<ApiResult<SessionOut>> {
  return call(() => client.POST('/v1/auth/login', { body: { phone, pin } }), false)
}

export function register(
  full_name: string,
  phone: string,
  email: string,
  pin: string,
  invite_code: string,
): Promise<ApiResult<SessionOut>> {
  return call(
    () =>
      client.POST('/v1/auth/register', {
        body: { full_name, phone, email, pin, invite_code },
      }),
    false,
  )
}

export async function logout(): Promise<void> {
  await attempt(() => client.POST('/v1/auth/logout'))
  accessToken = null
}

// ------------------------------------------------------------------ agenda y sincronización

export interface WireEvent {
  event_id: string
  type: string
  visit_id: string | null
  device_ts: string
  app_version: string
  payload: Record<string, unknown>
}

export function postSync(deviceId: string, events: WireEvent[], outboxPending: number): Promise<ApiResult<SyncOut>> {
  return call(() =>
    client.POST('/v1/sync', {
      headers: bearer(),
      body: {
        device_id: deviceId,
        sent_at: new Date().toISOString(),
        outbox_pending: outboxPending,
        events,
      },
    }),
  )
}

export function fetchState(cursor: number | null): Promise<ApiResult<StateOut>> {
  return call(() =>
    client.GET('/v1/me/state', {
      headers: bearer(),
      params: { query: cursor === null ? {} : { cursor } },
    }),
  )
}

// ------------------------------------------------------------------ notificaciones

export const notifications = {
  get: (): Promise<ApiResult<Preferences>> =>
    call(() => client.GET('/v1/notifications/preferences', { headers: bearer() })),

  update: (body: components['schemas']['PreferencesIn']): Promise<ApiResult<Preferences>> =>
    call(() => client.PUT('/v1/notifications/preferences', { headers: bearer(), body })),

  subscribe: (endpoint: string, p256dh: string, auth: string): Promise<ApiResult<Preferences>> =>
    call(() =>
      client.POST('/v1/notifications/push/subscriptions', {
        headers: bearer(),
        body: { endpoint, keys: { p256dh, auth } },
      }),
    ),

  unsubscribe: (endpoint: string): Promise<ApiResult<Preferences>> =>
    call(() =>
      client.POST('/v1/notifications/push/unsubscribe', {
        headers: bearer(),
        body: { endpoint },
      }),
    ),

  registerEmail: (email: string): Promise<ApiResult<components['schemas']['EmailStartOut']>> =>
    call(() =>
      client.POST('/v1/notifications/email', {
        headers: bearer(),
        body: { email },
      }),
    ),

  verifyEmail: (code: string): Promise<ApiResult<Preferences>> =>
    call(() =>
      client.POST('/v1/notifications/email/verify', {
        headers: bearer(),
        body: { code },
      }),
    ),

  removeEmail: (): Promise<ApiResult<Preferences>> =>
    call(() => client.DELETE('/v1/notifications/email', { headers: bearer() })),

  sendTest: (channel: 'push' | 'email' | 'all'): Promise<ApiResult<components['schemas']['TestOut']>> =>
    call(() =>
      client.POST('/v1/notifications/test', {
        headers: bearer(),
        body: { channel },
      }),
    ),
}

// ------------------------------------------------------------------ entrenar (práctica con médico virtual)

export type TrainingOverview = components['schemas']['OverviewOut']
export type TrainingScenarioSummary = components['schemas']['ScenarioSummary']
export type TrainingScenario = components['schemas']['ScenarioDetailOut']
export type TrainingProfile = components['schemas']['ProfileOut']
export type QuizResult = components['schemas']['QuizResultOut']
export type PracticeAttempt = components['schemas']['AttemptOut']
export type PracticeEvaluation = components['schemas']['EvaluationOut']
export type DoctorAvailability = components['schemas']['DoctorAvailability']

export const training = {
  overview: (): Promise<ApiResult<TrainingOverview>> =>
    call(() => client.GET('/v1/training/overview', { headers: bearer() })),

  scenario: (slug: string): Promise<ApiResult<TrainingScenario>> =>
    call(() =>
      client.GET('/v1/training/scenarios/{slug}', {
        headers: bearer(),
        params: { path: { slug } },
      }),
    ),

  submitQuiz: (slug: string, answers: Record<string, string>): Promise<ApiResult<QuizResult>> =>
    call(() =>
      client.POST('/v1/training/scenarios/{slug}/quiz', {
        headers: bearer(),
        params: { path: { slug } },
        body: { answers },
      }),
    ),

  saveProfile: (body: components['schemas']['ProfileIn']): Promise<ApiResult<TrainingProfile>> =>
    call(() => client.PUT('/v1/training/profile', { headers: bearer(), body })),

  start: (slug: string, audioOnly = false): Promise<ApiResult<PracticeAttempt>> =>
    call(() =>
      client.POST('/v1/training/attempts', {
        headers: bearer(),
        body: { scenario_slug: slug, audio_only: audioOnly },
      }),
    ),

  attempt: (id: string): Promise<ApiResult<PracticeAttempt>> =>
    call(() =>
      client.GET('/v1/training/attempts/{attempt_id}', {
        headers: bearer(),
        params: { path: { attempt_id: id } },
      }),
    ),

  end: (id: string): Promise<ApiResult<PracticeAttempt>> =>
    call(() =>
      client.POST('/v1/training/attempts/{attempt_id}/end', {
        headers: bearer(),
        params: { path: { attempt_id: id } },
      }),
    ),
}
