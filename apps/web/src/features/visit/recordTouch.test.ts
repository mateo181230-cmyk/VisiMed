import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { UnoDB } from '../../db/db'
import type { Ubicacion } from '../geo/tipos'
import { recordTouch, retryLocation, toWireLocation } from './recordTouch'

let n = 0
let db: UnoDB
beforeEach(() => {
  db = new UnoDB(`record-${++n}`)
})
afterEach(() => {
  db.close()
})

const lectura = (over: Partial<Ubicacion> = {}): Ubicacion => ({
  lat: 4.6765,
  lng: -74.0481,
  precision_m: 22,
  fix_ts: '2026-09-29T15:29:58.000Z',
  fuente: 'gps',
  permiso: 'granted',
  duracion_ms: 1400,
  error: null,
  ...over,
})
const sinLectura = (over: Partial<Ubicacion> = {}): Ubicacion =>
  lectura({
    lat: null,
    lng: null,
    precision_m: null,
    fix_ts: null,
    fuente: 'ninguna',
    duracion_ms: 8000,
    error: 'tiempo_agotado',
    ...over,
  })

/** Una lectura que el test resuelve a mano, para mirar qué pasa MIENTRAS se espera. */
function pendiente() {
  let resolver!: (u: Ubicacion) => void
  const promesa = new Promise<Ubicacion>((r) => (resolver = r))
  return { capturar: () => promesa, resolver }
}

describe('recordTouch: el toque se guarda al instante', () => {
  it('el evento existe ANTES de que llegue la ubicación (no depende del GPS)', async () => {
    const p = pendiente()
    const toque = recordTouch('arrival', 'v1', { database: db, capturar: p.capturar })
    await new Promise((r) => setTimeout(r, 20))

    const [enEspera] = await db.outbox.toArray()
    expect(enEspera).toMatchObject({ type: 'visit_arrived', visit_id: 'v1', status: 'capturing' })

    p.resolver(lectura())
    await toque
    const [listo] = await db.outbox.toArray()
    expect(listo!.status).toBe('pending')
    expect(listo!.payload).toMatchObject({
      location: { lat: 4.6765, lng: -74.0481, precision_m: 22, source: 'gps' },
      permission: 'granted',
      duration_ms: 1400,
      error: null,
    })
    expect(listo!.device_ts <= new Date().toISOString()).toBe(true)
  })

  it('«Terminé» usa su propio evento', async () => {
    await recordTouch('finish', 'v1', { database: db, capturar: async () => lectura() })
    const [row] = await db.outbox.toArray()
    expect(row).toMatchObject({ type: 'visit_finished', status: 'pending' })
  })

  it('sin ubicación el toque igual sale: location nula y el motivo en el diagnóstico', async () => {
    const u = await recordTouch('arrival', 'v1', { database: db, capturar: async () => sinLectura() })
    expect(u.fuente).toBe('ninguna')
    const [row] = await db.outbox.toArray()
    expect(row!.status).toBe('pending')
    expect(row!.payload).toMatchObject({ location: null, error: 'tiempo_agotado', duration_ms: 8000 })
  })

  it('si la captura lanzara una excepción, el toque no se queda atascado en «capturando»', async () => {
    await recordTouch('arrival', 'v1', {
      database: db,
      capturar: async () => {
        throw new Error('boom')
      },
    })
    const [row] = await db.outbox.toArray()
    expect(row).toMatchObject({ status: 'pending', payload: { location: null } })
  })

  it('un segundo toque mientras el primero espera su ubicación no duplica el evento', async () => {
    const p = pendiente()
    const a = recordTouch('arrival', 'v1', { database: db, capturar: p.capturar })
    const b = recordTouch('arrival', 'v1', { database: db, capturar: p.capturar })
    await new Promise((r) => setTimeout(r, 20))
    p.resolver(lectura())
    await Promise.all([a, b])
    expect(await db.outbox.count()).toBe(1)
  })

  it('llegada y salida de la misma visita son toques distintos', async () => {
    await recordTouch('arrival', 'v1', { database: db, capturar: async () => lectura() })
    await recordTouch('finish', 'v1', { database: db, capturar: async () => lectura() })
    expect((await db.outbox.toArray()).map((e) => e.type)).toEqual(['visit_arrived', 'visit_finished'])
  })
})

describe('retryLocation', () => {
  it('con una lectura nueva envía visit_location_retried con el momento correcto', async () => {
    await retryLocation('arrival', 'v1', { database: db, capturar: async () => lectura({ precision_m: 12 }) })
    const [row] = await db.outbox.toArray()
    expect(row).toMatchObject({ type: 'visit_location_retried', visit_id: 'v1', status: 'pending' })
    expect(row!.payload).toMatchObject({ moment: 'arrival', location: { precision_m: 12 } })
  })

  it('si vuelve a fallar no envía nada: el toque queda como estaba', async () => {
    const u = await retryLocation('finish', 'v1', { database: db, capturar: async () => sinLectura() })
    expect(u.fuente).toBe('ninguna')
    expect(await db.outbox.count()).toBe(0)
  })
})

describe('toWireLocation', () => {
  it('convierte la ubicación de la app a la forma del contrato', () => {
    expect(toWireLocation(lectura())).toEqual({
      lat: 4.6765,
      lng: -74.0481,
      precision_m: 22,
      fix_ts: '2026-09-29T15:29:58.000Z',
      source: 'gps',
    })
    expect(toWireLocation(lectura({ fuente: 'reutilizada' }))?.source).toBe('reused')
    expect(toWireLocation(sinLectura())).toBeNull()
  })
})
