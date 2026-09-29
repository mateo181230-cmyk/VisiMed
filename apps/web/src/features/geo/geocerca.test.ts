import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { clasificar, haversineM } from './geocerca'
import type { GeoEstado, Lectura, Referencia } from './tipos'

interface Caso {
  nombre: string
  lectura: Pick<Lectura, 'lat' | 'lng' | 'precision_m'> | null
  referencia: Referencia | null
  radio_m: number
  esperado: { estado: GeoEstado; distancia_m: number | null }
}

// Fuente de verdad compartida con el backend (T4.4): docs/contratos/geocerca-casos.json
const archivo = resolve(import.meta.dirname, '../../../../../docs/contratos/geocerca-casos.json')
const { casos } = JSON.parse(readFileSync(archivo, 'utf8')) as {
  casos: Caso[]
}

describe('geocerca: tabla compartida con el servidor', () => {
  it('tiene los 20 casos del plan (T4.1 ST5)', () => {
    expect(casos).toHaveLength(20)
  })

  it.each(casos.map((c) => [c.nombre, c] as const))('%s', (_nombre, c) => {
    expect(clasificar(c.lectura, c.referencia, c.radio_m)).toEqual(c.esperado)
  })
})

describe('haversine', () => {
  it('un grado de latitud son ~111,2 km', () => {
    expect(haversineM({ lat: 4, lng: -74 }, { lat: 5, lng: -74 })).toBeCloseTo(111_194.9, 0)
  })

  it('es simétrica y cero en el mismo punto', () => {
    const a = { lat: 4.6765, lng: -74.0481 }
    const b = { lat: 4.711, lng: -74.0721 }
    expect(haversineM(a, a)).toBe(0)
    expect(haversineM(a, b)).toBeCloseTo(haversineM(b, a), 6)
  })
})

describe('clasificar: reglas que no son un caso de la tabla', () => {
  const ref = { lat: 4.6765, lng: -74.0481 }

  it('el radio por defecto es el de institución (300 m): la mayoría de visitas son en hospitales', () => {
    const a = (m: number) => ({ lat: 4.6765 + m / 111_195, lng: ref.lng, precision_m: 40 })
    expect(clasificar(a(330), ref).estado).toBe('verificada') // 330 − 40 = 290 ≤ 300
    expect(clasificar(a(350), ref).estado).toBe('lejos') // 350 − 40 = 310 > 300
    expect(clasificar(a(190), ref, 150).estado).toBe('verificada') // un consultorio suelto usa 150 m
    expect(clasificar(a(250), ref, 150).estado).toBe('lejos')
  })

  it('una lectura reutilizada («Otro médico aquí») se clasifica igual que la original', () => {
    const lectura = { lat: 4.6765, lng: -74.0481, precision_m: 12 }
    expect(clasificar({ ...lectura }, ref)).toEqual(clasificar(lectura, ref))
  })
})
