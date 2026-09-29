import type { Clasificacion, Lectura, Referencia } from './tipos'

/** Radio medio de la Tierra. Debe ser idéntico en el backend (T4.4) para que ambos den la misma distancia. */
export const RADIO_TIERRA_M = 6_371_000

/** Por encima de este error de lectura no se puede verificar nada (doc 01 §9.3). */
export const PRECISION_MAX_UTIL_M = 100

/**
 * Radios de geocerca (PROPUESTA, pregunta Q6). La mayoría de visitas son en hospitales urbanos, así que el
 * radio por defecto es el de institución (300 m); 150 m queda para un consultorio independiente.
 */
export const RADIO_CONSULTORIO_M = 150
export const RADIO_INSTITUCION_M = 300

const rad = (grados: number): number => (grados * Math.PI) / 180

/** Distancia en metros (fórmula de haversine) entre dos puntos, sin redondear. */
export function haversineM(a: Referencia, b: Referencia): number {
  const dLat = rad(b.lat - a.lat)
  const dLng = rad(b.lng - a.lng)
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2
  return 2 * RADIO_TIERRA_M * Math.asin(Math.min(1, Math.sqrt(h)))
}

/**
 * Clasifica una lectura contra la referencia del consultorio (doc 01 §9.3).
 *
 * Orden de decisión (la tabla del doc no fija la precedencia; se fija aquí y en el backend igual):
 *  1. sin lectura → `sin_gps`
 *  2. `precision_m > 100` → `imprecisa` (una lectura de ±300 m no verifica ni desmiente nada)
 *  3. sin referencia → `sin_referencia`
 *  4. `d − precision_m ≤ R` → `verificada`, si no → `lejos`
 *
 * `d` se redondea a metros enteros (mitad hacia arriba) *antes* de comparar, de modo que TypeScript y
 * Python coinciden en los bordes. `reutilizada` («Otro médico aquí») no es un estado propio: la lectura se
 * copia de la llegada original y se clasifica igual; la marca vive en `Ubicacion.fuente`.
 *
 * Los mismos casos (`docs/contratos/geocerca-casos.json`) se prueban en el backend.
 */
export function clasificar(
  lectura: Pick<Lectura, 'lat' | 'lng' | 'precision_m'> | null,
  referencia: Referencia | null,
  radioM: number = RADIO_INSTITUCION_M,
): Clasificacion {
  if (!lectura) return { estado: 'sin_gps', distancia_m: null }
  if (lectura.precision_m > PRECISION_MAX_UTIL_M) {
    return {
      estado: 'imprecisa',
      distancia_m: referencia ? distanciaEntera(lectura, referencia) : null,
    }
  }
  if (!referencia) return { estado: 'sin_referencia', distancia_m: null }
  const distancia_m = distanciaEntera(lectura, referencia)
  return {
    estado: distancia_m - lectura.precision_m <= radioM ? 'verificada' : 'lejos',
    distancia_m,
  }
}

function distanciaEntera(lectura: Referencia, referencia: Referencia): number {
  return Math.floor(haversineM(lectura, referencia) + 0.5)
}
