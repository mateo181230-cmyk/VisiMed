import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  TIMEOUT_LECTURA_MS,
  capturarUbicacion,
  contextoSeguro,
  estadoPermiso,
  leerPermiso,
  observarPermiso,
} from './capturar'

type Ok = (pos: GeolocationPosition) => void
type Fallo = (err: GeolocationPositionError) => void

const posicion = (accuracy: number, lat = 4.6765, lng = -74.0481): GeolocationPosition =>
  ({ coords: { latitude: lat, longitude: lng, accuracy }, timestamp: Date.now() }) as GeolocationPosition
const error = (code: number): GeolocationPositionError => ({ code, message: '' }) as GeolocationPositionError

type Respuesta = { ok: GeolocationPosition } | { fallo: number } | 'nunca'

/** GPS falso: solo `getCurrentPosition`. Si el código usara `watchPosition` (seguimiento) fallaría la prueba. */
function gpsFalso(respuesta: Respuesta, despuesMs = 0) {
  const getCurrentPosition = vi.fn((ok: Ok, fallo: Fallo) => {
    if (respuesta === 'nunca') return
    setTimeout(() => ('ok' in respuesta ? ok(respuesta.ok) : fallo(error(respuesta.fallo))), despuesMs)
  })
  const geo = { getCurrentPosition } as unknown as Geolocation
  return { geo, getCurrentPosition }
}

const permisos = (estado: PermissionState) =>
  ({ query: vi.fn().mockResolvedValue({ state: estado }) }) as unknown as Pick<Permissions, 'query'>

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-09-29T14:32:00Z'))
  localStorage.clear()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('capturarUbicacion: una sola lectura por toque', () => {
  it('pide la posición UNA vez, con alta precisión y sin reutilizar una guardada', async () => {
    const g = gpsFalso({ ok: posicion(18) }, 1200)
    const p = capturarUbicacion({ geo: g.geo, permisos: permisos('granted') })
    await vi.advanceTimersByTimeAsync(1200)
    const r = await p
    expect(g.getCurrentPosition).toHaveBeenCalledTimes(1)
    expect(g.getCurrentPosition).toHaveBeenCalledWith(expect.any(Function), expect.any(Function), {
      enableHighAccuracy: true,
      maximumAge: 0,
      timeout: TIMEOUT_LECTURA_MS,
    })
    expect(r).toMatchObject({
      fuente: 'gps',
      precision_m: 18,
      lat: 4.6765,
      lng: -74.0481,
      permiso: 'granted',
      error: null,
      duracion_ms: 1200,
    })
    expect(r.fix_ts).toBe('2026-09-29T14:32:00.000Z')
  })

  it('devuelve la lectura aunque sea imprecisa: clasificarla no es trabajo de la captura', async () => {
    const g = gpsFalso({ ok: posicion(480) })
    const p = capturarUbicacion({ geo: g.geo, permisos: permisos('granted') })
    await vi.advanceTimersByTimeAsync(0)
    await expect(p).resolves.toMatchObject({ fuente: 'gps', precision_m: 480 })
  })

  it('no hay reintento ni segunda lectura si falla: una lectura, un resultado', async () => {
    const g = gpsFalso({ fallo: 3 })
    const p = capturarUbicacion({ geo: g.geo, permisos: permisos('granted') })
    await vi.advanceTimersByTimeAsync(TIMEOUT_LECTURA_MS)
    await expect(p).resolves.toMatchObject({ fuente: 'ninguna', error: 'tiempo_agotado' })
    expect(g.getCurrentPosition).toHaveBeenCalledTimes(1)
  })

  it('el peor caso (el navegador nunca responde) termina en el tope y sin excepción', async () => {
    const g = gpsFalso('nunca')
    const p = capturarUbicacion({ geo: g.geo, permisos: permisos('granted') })
    await vi.advanceTimersByTimeAsync(TIMEOUT_LECTURA_MS)
    const r = await p
    expect(r).toMatchObject({ fuente: 'ninguna', error: 'tiempo_agotado', lat: null })
    expect(r.duracion_ms).toBe(TIMEOUT_LECTURA_MS)
    expect(TIMEOUT_LECTURA_MS).toBeLessThanOrEqual(10_000)
  })

  it('distingue «posición no disponible» de «tiempo agotado»', async () => {
    const g = gpsFalso({ fallo: 2 })
    const p = capturarUbicacion({ geo: g.geo, permisos: permisos('granted') })
    await vi.advanceTimersByTimeAsync(0)
    await expect(p).resolves.toMatchObject({ fuente: 'ninguna', error: 'no_disponible' })
  })

  it('descarta una lectura con coordenadas inválidas', async () => {
    const g = gpsFalso({ ok: posicion(Number.NaN) })
    const p = capturarUbicacion({ geo: g.geo, permisos: permisos('granted') })
    await vi.advanceTimersByTimeAsync(0)
    await expect(p).resolves.toMatchObject({ fuente: 'ninguna', lat: null })
  })

  it('acepta un tope propio (para las pruebas y el diagnóstico)', async () => {
    const g = gpsFalso('nunca')
    const p = capturarUbicacion({ geo: g.geo, permisos: permisos('granted'), timeoutMs: 3000 })
    await vi.advanceTimersByTimeAsync(3000)
    await expect(p).resolves.toMatchObject({ error: 'tiempo_agotado', duracion_ms: 3000 })
  })
})

describe('capturarUbicacion: permiso y soporte', () => {
  it('permiso negado → «ninguna» de inmediato, sin encender el GPS y sin excepción', async () => {
    const g = gpsFalso({ ok: posicion(10) })
    const r = await capturarUbicacion({ geo: g.geo, permisos: permisos('denied') })
    expect(r).toMatchObject({ fuente: 'ninguna', permiso: 'denied', error: 'permiso_denegado', lat: null })
    expect(r.duracion_ms).toBeLessThan(1000)
    expect(g.getCurrentPosition).not.toHaveBeenCalled()
  })

  it('un permiso negado que llega durante la lectura también devuelve «ninguna»', async () => {
    const g = gpsFalso({ fallo: 1 })
    const p = capturarUbicacion({ geo: g.geo, permisos: permisos('prompt') })
    await vi.advanceTimersByTimeAsync(0)
    await expect(p).resolves.toMatchObject({ fuente: 'ninguna', permiso: 'denied', error: 'permiso_denegado' })
  })

  it('sin Geolocation API → «ninguna» con error sin_soporte', async () => {
    // En jsdom `navigator.geolocation` no existe.
    const r = await capturarUbicacion({ permisos: permisos('prompt') })
    expect(r).toMatchObject({ fuente: 'ninguna', error: 'sin_soporte' })
  })

  it('fuera de un contexto seguro (HTTP) lo distingue de un permiso negado', async () => {
    vi.stubGlobal('isSecureContext', false)
    const g = gpsFalso({ ok: posicion(10) })
    const r = await capturarUbicacion({ geo: g.geo })
    expect(contextoSeguro()).toBe(false)
    expect(r).toMatchObject({ fuente: 'ninguna', error: 'contexto_inseguro' })
    expect(g.getCurrentPosition).not.toHaveBeenCalled()
  })
})

describe('permiso de ubicación', () => {
  it('si la Permissions API falla o no responde, sigue como «prompt»', async () => {
    const colgada = { query: vi.fn(() => new Promise(() => {})) } as unknown as Pick<Permissions, 'query'>
    const pendiente = leerPermiso(colgada)
    await vi.advanceTimersByTimeAsync(600)
    await expect(pendiente).resolves.toBe('prompt')
    const rota = { query: vi.fn().mockRejectedValue(new Error('x')) } as unknown as Pick<Permissions, 'query'>
    await expect(leerPermiso(rota)).resolves.toBe('prompt')
  })

  it('sin Permissions API confía en la última lectura que salió bien', async () => {
    // jsdom no trae `navigator.permissions`.
    expect(await estadoPermiso()).toBe('prompt')
    const g = gpsFalso({ ok: posicion(30) })
    const p = capturarUbicacion({ geo: g.geo })
    await vi.advanceTimersByTimeAsync(0)
    await p
    expect(await estadoPermiso()).toBe('granted')
    // Una lectura con permiso negado borra ese recuerdo.
    const negada = gpsFalso({ fallo: 1 })
    const q = capturarUbicacion({ geo: negada.geo })
    await vi.advanceTimersByTimeAsync(0)
    await q
    expect(await estadoPermiso()).toBe('prompt')
  })

  it('avisa cuando el usuario cambia el permiso en los ajustes y deja de avisar al cancelar', async () => {
    const oyentes = new Set<() => void>()
    const estado = {
      state: 'denied' as PermissionState,
      addEventListener: (_: string, fn: () => void) => oyentes.add(fn),
      removeEventListener: (_: string, fn: () => void) => oyentes.delete(fn),
    }
    vi.stubGlobal('navigator', { permissions: { query: vi.fn().mockResolvedValue(estado) } })
    const vistos: PermissionState[] = []
    const dejar = observarPermiso((e) => vistos.push(e))
    await vi.advanceTimersByTimeAsync(0)
    estado.state = 'granted'
    oyentes.forEach((fn) => fn())
    expect(vistos).toEqual(['granted'])
    dejar()
    expect(oyentes.size).toBe(0)
  })
})
