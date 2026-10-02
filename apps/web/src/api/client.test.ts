import { afterEach, describe, expect, it, vi } from 'vitest'

const NativeRequest = globalThis.Request

afterEach(() => vi.unstubAllGlobals())

async function failure(status: number, body: unknown) {
  vi.resetModules()
  vi.stubGlobal('Request', class extends NativeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(typeof input === 'string' ? new URL(input, 'http://localhost') : input, init)
    }
  })
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  })))
  const { postSync } = await import('./client')
  return postSync('device', [], 0)
}

describe('errores de validación de sincronización', () => {
  it('reconoce el error estructurado de un evento del backend', async () => {
    expect(await failure(422, { detail: { code: 'invalid_payload', message: 'Evento inválido' } }))
      .toMatchObject({ ok: false, kind: 'client', status: 422, eventValidation: true, code: 'invalid_payload' })
  })

  it('reconoce la validación FastAPI de un campo del evento', async () => {
    expect(await failure(422, { detail: [{ loc: ['body', 'events', 0, 'event_id'], type: 'uuid_parsing', msg: 'Invalid UUID' }] }))
      .toMatchObject({ ok: false, kind: 'client', eventValidation: true, code: 'invalid_event_envelope' })
  })

  it.each([
    [403, { detail: { code: 'forbidden', message: 'Forbidden' } }],
    [404, { detail: 'Not Found' }],
    [408, { detail: 'Request Timeout' }],
    [413, { detail: { code: 'invalid_payload', message: 'Proxy response' } }],
    [422, { detail: [{ loc: ['body', 'device_id'], type: 'uuid_parsing', msg: 'Invalid UUID' }] }],
    [422, { detail: [{ loc: ['body', 'events'], type: 'too_long', msg: 'Too many events' }] }],
    [422, { detail: [{ loc: ['body', 'events', 0, 'event_id'] }] }],
    [422, { detail: { code: 'unknown', message: 'Unknown error' } }],
    [422, { detail: { code: ['invalid_payload'], message: 'Invalid error code' } }],
  ])('no convierte el error HTTP %i de infraestructura/sobre en rechazo de visitas', async (status, body) => {
    const result = await failure(status as number, body)
    expect(result).toMatchObject({ ok: false, kind: 'client' })
    expect(result).not.toHaveProperty('eventValidation', true)
  })
})
