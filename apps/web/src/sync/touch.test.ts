import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { ApiResult, StateOut, SyncOut, WireEvent } from '../api/client'
import { type InstitutionRow, type OutboxRow, UnoDB, type VisitRow } from '../db/db'
import { SyncEngine, type SyncPort } from './engine'
import { visitArrived } from './events'
import { completeCapture, enqueue, enqueueCapturing, recoverCapturing } from './outbox'
import { overlay } from './overlay'

const REF = { lat: 4.6765, lng: -74.0481 }
const hospital: InstitutionRow = {
  id: 'i1',
  name: 'Hospital San Rafael',
  address: null,
  city: null,
  lat: REF.lat,
  lng: REF.lng,
  radius_m: 300,
}
const visit: VisitRow = {
  id: 'v1',
  doctor_id: 'd1',
  institution_id: 'i1',
  primary_line_id: 'l1',
  line_ids: ['l1'],
  scheduled_at: '2026-09-29T15:30:00Z',
  status: 'scheduled',
  planned_by: 'rep',
  not_done_reason: null,
  updated_at: '2026-09-29T12:00:00Z',
}
const at = (metersNorth: number, precision = 15) => ({
  lat: REF.lat + metersNorth / 111_195,
  lng: REF.lng,
  precision_m: precision,
  fix_ts: '2026-09-29T15:29:58Z',
  source: 'gps' as const,
})

let seq = 0
const ev = (type: string, payload: Record<string, unknown>, over: Partial<OutboxRow> = {}): OutboxRow => ({
  seq: ++seq,
  event_id: `e${seq}`,
  type,
  visit_id: 'v1',
  device_ts: '2026-09-29T15:30:00Z',
  payload,
  status: 'pending',
  attempts: 0,
  created_at: '2026-09-29T15:30:00Z',
  ...over,
})

const base = { visits: [visit], doctors: [], institutions: [hospital] }
const visitOf = (events: OutboxRow[], snapshot = base) => overlay(snapshot, events).visits.get('v1')!

describe('overlay: Llegué', () => {
  it('pasa a «en visita» al instante, con la hora del toque y la ubicación clasificada', () => {
    const v = visitOf([ev('visit_arrived', { location: at(120) })])
    expect(v).toMatchObject({ status: 'in_progress', arrived_at: '2026-09-29T15:30:00Z' })
    expect(v.arrival_geo).toEqual({ state: 'verificada', distance_m: 120, precision_m: 15 })
  })

  it('a 850 m queda «lejos» con la distancia, y la visita sigue válida', () => {
    const v = visitOf([ev('visit_arrived', { location: at(850) })])
    expect(v.status).toBe('in_progress')
    expect(v.arrival_geo).toMatchObject({ state: 'lejos', distance_m: 850 })
  })

  it('sin lectura queda «sin GPS» pero el toque vale', () => {
    const v = visitOf([ev('visit_arrived', { location: null })])
    expect(v.status).toBe('in_progress')
    expect(v.arrival_geo).toEqual({ state: 'sin_gps', distance_m: null, precision_m: null })
  })

  it('una institución sin coordenadas deja «sin referencia»', () => {
    const v = visitOf([ev('visit_arrived', { location: at(0) })], {
      ...base,
      institutions: [{ ...hospital, lat: null, lng: null }],
    })
    expect(v.arrival_geo?.state).toBe('sin_referencia')
  })

  it('un toque que aún espera su ubicación ya se ve (capturing es un estado vivo)', () => {
    const v = visitOf([ev('visit_arrived', { location: null }, { status: 'capturing' })])
    expect(v.status).toBe('in_progress')
  })

  it('un toque rechazado desaparece de la pantalla', () => {
    const v = visitOf([ev('visit_arrived', { location: at(0) }, { status: 'rejected' })])
    expect(v.status).toBe('scheduled')
  })

  it('es idempotente: si la foto del servidor ya la tiene en visita, gana la del servidor', () => {
    const server: VisitRow = {
      ...visit,
      status: 'in_progress',
      arrived_at: '2026-09-29T15:30:01Z',
      arrival_geo: { state: 'verificada', distance_m: 118, precision_m: 15 },
    }
    const v = visitOf([ev('visit_arrived', { location: at(850) }, { status: 'confirmed' })], {
      ...base,
      visits: [server],
    })
    expect(v.arrival_geo).toEqual(server.arrival_geo)
    expect(v.arrived_at).toBe('2026-09-29T15:30:01Z')
  })
})

describe('overlay: Terminé', () => {
  const arrived = ev('visit_arrived', { location: at(50) })

  it('cierra la visita en curso con su propia ubicación', () => {
    const v = visitOf([arrived, ev('visit_finished', { location: at(900) }, { device_ts: '2026-09-29T16:00:00Z' })])
    expect(v).toMatchObject({ status: 'finished', finished_at: '2026-09-29T16:00:00Z' })
    expect(v.arrival_geo?.state).toBe('verificada')
    expect(v.finish_geo).toMatchObject({ state: 'lejos', distance_m: 900 })
  })

  it('Terminé sin Llegué se acepta: queda terminada y sin hora de llegada', () => {
    const v = visitOf([ev('visit_finished', { location: at(10) })])
    expect(v.status).toBe('finished')
    expect(v.arrived_at).toBeUndefined()
  })

  it('no reabre ni pisa una visita ya terminada', () => {
    const v = visitOf([
      ev('visit_finished', { location: at(10) }),
      ev('visit_finished', { location: at(900) }, { device_ts: '2026-09-29T17:00:00Z' }),
    ])
    expect(v.finish_geo?.state).toBe('verificada')
  })
})

describe('overlay: reintentar ubicación', () => {
  it('reemplaza una ubicación que no servía (sin GPS → verificada)', () => {
    const v = visitOf([
      ev('visit_arrived', { location: null }),
      ev('visit_location_retried', { moment: 'arrival', location: at(60) }),
    ])
    expect(v.arrival_geo).toEqual({ state: 'verificada', distance_m: 60, precision_m: 15 })
  })

  it('también reemplaza una imprecisa', () => {
    const v = visitOf([
      ev('visit_arrived', { location: at(60, 400) }),
      ev('visit_location_retried', { moment: 'arrival', location: at(60, 20) }),
    ])
    expect(v.arrival_geo?.state).toBe('verificada')
  })

  it('no toca una ubicación ya verificada ni una «lejos»', () => {
    const lejos = visitOf([
      ev('visit_arrived', { location: at(850) }),
      ev('visit_location_retried', { moment: 'arrival', location: at(10) }),
    ])
    expect(lejos.arrival_geo?.state).toBe('lejos')
  })

  it('el reintento de la salida solo cambia la salida', () => {
    const v = visitOf([
      ev('visit_arrived', { location: at(40) }),
      ev('visit_finished', { location: null }),
      ev('visit_location_retried', { moment: 'finish', location: at(30) }),
    ])
    expect(v.arrival_geo?.state).toBe('verificada')
    expect(v.finish_geo?.state).toBe('verificada')
  })
})

// ---------------------------------------------------------------- cola: captura del toque

let n = 0
let db: UnoDB

beforeEach(() => {
  db = new UnoDB(`touch-${++n}`)
})
afterEach(() => {
  db.close()
})

const arrivalSpec = () => visitArrived('v1', { location: null })

describe('cola: el toque se guarda ya y la ubicación se adjunta después', () => {
  it('un toque en captura no se envía: espera su ubicación', async () => {
    await enqueueCapturing(arrivalSpec(), db)
    const [row] = await db.outbox.toArray()
    expect(row).toMatchObject({ type: 'visit_arrived', status: 'capturing', visit_id: 'v1' })
    expect(await db.outbox.where('status').equals('pending').count()).toBe(0)
  })

  it('al llegar la ubicación se une al mismo evento y pasa a pendiente', async () => {
    const id = await enqueueCapturing(arrivalSpec(), db)
    await completeCapture(id, { location: at(10), permission: 'granted', duration_ms: 1500, error: null }, db)
    const [row] = await db.outbox.toArray()
    expect(row!.status).toBe('pending')
    expect(row!.payload).toMatchObject({ location: { precision_m: 15 }, permission: 'granted', duration_ms: 1500 })
  })

  it('completar dos veces no revive ni pisa un evento que ya no está en captura', async () => {
    const id = await enqueueCapturing(arrivalSpec(), db)
    await completeCapture(id, { location: at(10) }, db)
    await db.outbox.where('event_id').equals(id).modify({ status: 'confirmed' })
    await completeCapture(id, { location: null }, db)
    const [row] = await db.outbox.toArray()
    expect(row!.status).toBe('confirmed')
    expect(row!.payload).toMatchObject({ location: { precision_m: 15 } })
  })

  it('si la app se cerró en medio de la captura, el toque NO se pierde: sale sin ubicación', async () => {
    // Un toque que quedó en captura de una sesión anterior (esta pestaña no lo está capturando).
    await db.outbox.add({
      event_id: 'huerfano',
      type: 'visit_arrived',
      visit_id: 'v1',
      device_ts: '2026-09-29T15:30:00Z',
      payload: { location: null },
      status: 'capturing',
      attempts: 0,
      created_at: '2026-09-29T15:30:00Z',
    })
    expect(await recoverCapturing(db)).toBe(1)
    const [row] = await db.outbox.toArray()
    expect(row).toMatchObject({ status: 'pending', payload: { location: null, error: 'interrupted' } })
  })

  it('la recuperación no toca un toque que esta pestaña sigue capturando', async () => {
    const vivo = await enqueueCapturing(arrivalSpec(), db)
    expect(await recoverCapturing(db)).toBe(0)
    expect((await db.outbox.toArray())[0]!.status).toBe('capturing')
    await completeCapture(vivo, { location: null }, db)
  })
})

class FakePort implements SyncPort {
  sent: WireEvent[] = []
  async postSync(_d: string, events: WireEvent[]): Promise<ApiResult<SyncOut>> {
    this.sent.push(...events)
    return {
      ok: true,
      data: {
        server_time: '2026-09-29T12:00:00Z',
        clock_skew_s: 0,
        results: events.map((e) => ({ event_id: e.event_id, status: 'applied' as const })),
      },
    }
  }
  async fetchState(): Promise<ApiResult<StateOut>> {
    return {
      ok: true,
      data: {
        server_time: '2026-09-29T12:00:00Z',
        cursor: 1,
        full: true,
        timezone: 'America/Bogota',
        lines: [],
        products: [],
        institutions: [],
        doctors: [],
        visits: [],
        reports: [],
        config: { reminder_options: [0], window_past_days: 7, window_future_days: 14 },
      },
    }
  }
}

describe('motor de sincronización y toques', () => {
  it('no envía un toque en captura, y al arrancar rescata los huérfanos y los envía sin ubicación', async () => {
    const port = new FakePort()
    const engine = new SyncEngine(port, db)
    await db.outbox.add({
      event_id: 'huerfano',
      type: 'visit_arrived',
      visit_id: 'v1',
      device_ts: '2026-09-29T15:30:00Z',
      payload: { location: null },
      status: 'capturing',
      attempts: 0,
      created_at: '2026-09-29T15:30:00Z',
    })
    await engine.start()
    await engine.run(true)
    engine.stop()
    expect(port.sent.map((e) => e.event_id)).toEqual(['huerfano'])
    expect(port.sent[0]!.payload).toMatchObject({ location: null, error: 'interrupted' })
  })

  it('un toque que aún se está capturando en esta sesión espera y no se envía', async () => {
    const port = new FakePort()
    const engine = new SyncEngine(port, db)
    const id = await enqueueCapturing(arrivalSpec(), db)
    await enqueue({ type: 'visit_not_done', visitId: 'v2', payload: { reason: 'other' } }, db)
    await engine.run(true)
    expect(port.sent.map((e) => e.type)).toEqual(['visit_not_done'])
    await completeCapture(id, { location: null }, db)
    await engine.run(true)
    expect(port.sent.map((e) => e.type)).toEqual(['visit_not_done', 'visit_arrived'])
  })
})
