import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { ApiResult, StateOut, SyncOut, WireEvent } from '../api/client'
import { UnoDB, getMeta } from '../db/db'
import { EXPIRY_MS, backoffDelayMs } from './backoff'
import { SyncEngine, type SyncPort } from './engine'
import { doctorCreated, visitNotDone, visitScheduled } from './events'
import { enqueue, retryExpired } from './outbox'

let n = 0
const LINE = 'line-1'

function state(over: Partial<StateOut> = {}): StateOut {
  return {
    server_time: '2026-09-29T12:00:00Z',
    cursor: 5,
    full: true,
    timezone: 'America/Bogota',
    lines: [{ id: LINE, code: 'GASTRU', name: 'GASTRU', active: true }],
    products: [],
    institutions: [],
    doctors: [],
    visits: [],
    reports: [],
    config: { reminder_options: [0, 30], window_past_days: 7, window_future_days: 14 },
    ...over,
  }
}

class FakePort implements SyncPort {
  syncCalls: WireEvent[][] = []
  stateCalls: (number | null)[] = []
  syncResult: (events: WireEvent[]) => ApiResult<SyncOut> = (events) => ({
    ok: true,
    data: {
      server_time: '2026-09-29T12:00:00Z',
      clock_skew_s: 0,
      results: events.map((e) => ({ event_id: e.event_id, status: 'applied' as const })),
    },
  })
  stateResult: () => ApiResult<StateOut> = () => ({ ok: true, data: state() })
  async postSync(_d: string, events: WireEvent[]): Promise<ApiResult<SyncOut>> {
    this.syncCalls.push(events)
    return this.syncResult(events)
  }
  async fetchState(cursor: number | null): Promise<ApiResult<StateOut>> {
    this.stateCalls.push(cursor)
    return this.stateResult()
  }
}

let db: UnoDB
let port: FakePort
let engine: SyncEngine
let clock: number

beforeEach(() => {
  db = new UnoDB(`test-${++n}`)
  port = new FakePort()
  clock = new Date('2026-09-29T12:00:00Z').getTime()
  engine = new SyncEngine(port, db, { now: () => clock, random: () => 0.5 })
})

afterEach(async () => {
  engine.stop()
  db.close()
})

const schedule = (id: string) =>
  enqueue(visitScheduled(id, { doctor_id: 'd1', line_ids: [LINE], scheduled_at: '2026-09-29T16:00:00Z' }), db)

describe('subida de la cola', () => {
  it('envía en orden, confirma y luego baja el estado', async () => {
    await enqueue(doctorCreated({ doctor_id: 'd1', full_name: 'Dra. X', default_line_id: LINE }), db)
    await schedule('v1')
    await schedule('v2')

    await engine.run(true)

    expect(port.syncCalls).toHaveLength(1)
    expect(port.syncCalls[0]!.map((e) => e.type)).toEqual(['doctor_created', 'visit_scheduled', 'visit_scheduled'])
    expect(engine.getState()).toBe('idle')
    // Tras la bajada, lo confirmado ya está en la foto del servidor y sale de la cola.
    expect(await db.outbox.count()).toBe(0)
    expect(await getMeta<number>('cursor', db)).toBe(5)
    expect(await getMeta<string>('timezone', db)).toBe('America/Bogota')
  })

  it('un evento duplicado o aplicado queda confirmado; uno rechazado queda con su motivo', async () => {
    await schedule('v1')
    await schedule('v2')
    port.syncResult = (events) => ({
      ok: true,
      data: {
        server_time: 'x',
        clock_skew_s: 0,
        results: [
          { event_id: events[0]!.event_id, status: 'duplicate' },
          { event_id: events[1]!.event_id, status: 'rejected', reason: 'unknown_doctor' },
        ],
      },
    })
    await engine.run(true)
    const rows = await db.outbox.toArray()
    expect(rows).toHaveLength(1) // el confirmado se purgó tras la bajada
    expect(rows[0]).toMatchObject({ status: 'rejected', reason: 'unknown_doctor' })
  })

  it('cada evento viaja con el app_version y el device_ts del toque', async () => {
    await schedule('v1')
    await engine.run(true)
    const sent = port.syncCalls[0]![0]!
    expect(sent.app_version).toBeTruthy()
    expect(new Date(sent.device_ts).toString()).not.toBe('Invalid Date')
    expect(sent.visit_id).toBe('v1')
  })

  it('envía por lotes de 100', async () => {
    for (let i = 0; i < 230; i++) await schedule(`v${i}`)
    await engine.run(true)
    expect(port.syncCalls.map((c) => c.length)).toEqual([100, 100, 30])
  })

  it('no reenvía lo ya confirmado', async () => {
    await schedule('v1')
    await engine.run(true)
    await engine.run(true)
    expect(port.syncCalls).toHaveLength(1)
  })
})

describe('sin red, servidor caído y sesión vencida', () => {
  it('sin red: todo queda en la cola, el estado es «offline» y se reintenta al volver', async () => {
    await schedule('v1')
    port.syncResult = () => ({ ok: false, kind: 'network' })
    await engine.run(true)
    expect(engine.getState()).toBe('offline')
    let rows = await db.outbox.toArray()
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ status: 'pending', attempts: 1 })

    // Dentro de la espera de reintento no se vuelve a intentar…
    port.syncCalls.length = 0
    clock += 30_000
    await engine.run(false)
    expect(port.syncCalls).toHaveLength(0)
    // …pero al volver la red (force) sí.
    port.syncResult = new FakePort().syncResult
    await engine.run(true)
    expect(engine.getState()).toBe('idle')
    rows = await db.outbox.toArray()
    expect(rows).toHaveLength(0)
  })

  it('el retroceso crece 1-2-4-8 min con ±20 % de variación', () => {
    const at = (attempt: number, r: number) => backoffDelayMs(attempt, () => r)
    expect([1, 2, 3, 4, 5, 9].map((a) => at(a, 0.5))).toEqual([60_000, 120_000, 240_000, 480_000, 480_000, 480_000])
    expect(at(1, 0)).toBe(48_000)
    expect(at(1, 1)).toBe(72_000)
  })

  it('servidor caído (5xx): estado «error» y no se pierde nada', async () => {
    await schedule('v1')
    port.syncResult = () => ({ ok: false, kind: 'server', status: 503 })
    await engine.run(true)
    expect(engine.getState()).toBe('error')
    expect(await db.outbox.count()).toBe(1)
  })

  it('sesión vencida: estado «auth», los eventos se conservan', async () => {
    await schedule('v1')
    port.syncResult = () => ({ ok: false, kind: 'auth', status: 401 })
    await engine.run(true)
    expect(engine.getState()).toBe('auth')
    expect((await db.outbox.toArray())[0]!.status).toBe('pending')
  })

  it('a las 24 h sin éxito el evento pasa a «vencido» y se reintenta con un toque', async () => {
    await schedule('v1')
    port.syncResult = () => ({ ok: false, kind: 'network' })
    await engine.run(true)
    clock += EXPIRY_MS + 60_000
    // el reloj real de created_at es "ahora"; fuerza el vencimiento moviendo la fecha de creación
    await db.outbox.toCollection().modify({ created_at: new Date(clock - EXPIRY_MS - 1000).toISOString() })
    await engine.run(true)
    expect((await db.outbox.toArray())[0]!.status).toBe('expired')

    port.syncResult = new FakePort().syncResult
    expect(await retryExpired(db)).toBe(1)
    await engine.run(true)
    expect(await db.outbox.count()).toBe(0)
  })

  it('al arrancar, un envío que quedó a medias vuelve a la cola', async () => {
    await schedule('v1')
    await db.outbox.toCollection().modify({ status: 'sending' })
    await engine.start()
    await engine.run(true)
    expect(port.syncCalls.flat().length).toBeGreaterThan(0)
  })
})

describe('errores 4xx', () => {
  it('un evento que el servidor no acepta se aísla y los demás siguen', async () => {
    await schedule('good1')
    await schedule('bad')
    await schedule('good2')
    port.syncResult = (events) =>
      events.some((e) => e.visit_id === 'bad')
        ? events.length > 1
          ? { ok: false, kind: 'client', status: 422 }
          : { ok: false, kind: 'client', status: 422, code: 'invalid_payload' }
        : {
            ok: true,
            data: {
              server_time: 'x',
              clock_skew_s: 0,
              results: events.map((e) => ({ event_id: e.event_id, status: 'applied' as const })),
            },
          }
    await engine.run(true)
    const rows = await db.outbox.toArray()
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ visit_id: 'bad', status: 'rejected', reason: 'invalid_payload' })
  })
})

describe('bajada de estado', () => {
  it('estado completo reemplaza la foto; el incremental solo actualiza', async () => {
    const visit = (id: string, at: string) => ({
      id,
      doctor_id: 'd1',
      institution_id: null,
      primary_line_id: LINE,
      line_ids: [LINE],
      scheduled_at: at,
      status: 'scheduled',
      planned_by: 'rep',
      not_done_reason: null,
      updated_at: at,
      arrived_at: null,
      finished_at: null,
      arrival_geo: null,
      finish_geo: null,
    })
    port.stateResult = () => ({
      ok: true,
      data: state({
        full: true,
        cursor: 3,
        visits: [visit('a', '2026-09-29T15:00:00Z'), visit('b', '2026-09-29T16:00:00Z')],
      }),
    })
    await engine.run(true)
    expect(await db.visits.count()).toBe(2)
    expect(port.stateCalls).toEqual([null])

    port.stateResult = () => ({
      ok: true,
      data: state({ full: false, cursor: 4, visits: [visit('b', '2026-09-29T17:00:00Z')] }),
    })
    await engine.run(true)
    expect(port.stateCalls).toEqual([null, 3]) // pide desde el cursor guardado
    expect(await db.visits.count()).toBe(2)
    expect((await db.visits.get('b'))!.scheduled_at).toBe('2026-09-29T17:00:00Z')
    expect(await getMeta<number>('cursor', db)).toBe(4)

    port.stateResult = () => ({
      ok: true,
      data: state({ full: true, cursor: 1, visits: [visit('c', '2026-09-29T18:00:00Z')] }),
    })
    await engine.run(true)
    expect((await db.visits.toArray()).map((v) => v.id)).toEqual(['c']) // full: reemplaza
  })

  it('una bajada que falla no borra ni marca nada', async () => {
    port.stateResult = () => ({ ok: false, kind: 'network' })
    await engine.run(true)
    expect(engine.getState()).toBe('offline')
  })

  it('mantiene los eventos confirmados durante la bajada si se confirmaron después de que empezó', async () => {
    await schedule('v1')
    await engine.run(true)
    // El servidor confirmó justo después de empezar una bajada: no se debe purgar todavía.
    await db.outbox.add({
      event_id: 'late',
      type: 'visit_not_done',
      visit_id: 'v1',
      device_ts: new Date(clock).toISOString(),
      payload: { reason: 'other' },
      status: 'confirmed',
      confirmed_at: new Date(clock + 5000).toISOString(),
      attempts: 1,
      created_at: new Date(clock).toISOString(),
    })
    await engine.run(true)
    expect((await db.outbox.toArray()).map((r) => r.event_id)).toEqual(['late'])
  })
})

describe('un solo ciclo a la vez', () => {
  it('llamadas simultáneas a run() no envían dos veces el mismo evento', async () => {
    await schedule('v1')
    await Promise.all([engine.run(true), engine.run(true), engine.run(true)])
    await engine.run(true)
    expect(port.syncCalls.flat().filter((e) => e.visit_id === 'v1')).toHaveLength(1)
  })

  it('el evento «no se realizó» se encola con su motivo', async () => {
    await enqueue(visitNotDone('v1', 'doctor_unavailable'), db)
    const [row] = await db.outbox.toArray()
    expect(row).toMatchObject({ type: 'visit_not_done', visit_id: 'v1', payload: { reason: 'doctor_unavailable' } })
  })
})
