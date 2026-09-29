/** Tipos del módulo de ubicación (doc 01 §9.1). La ubicación solo se captura en Llegué y Terminé. */

/** `gps`: lectura de alta precisión tomada en el toque · `reutilizada`: «Otro médico aquí» (T4.6) ·
 *  `ninguna`: no hubo lectura. El navegador no dice qué sensor produjo la lectura (GPS, Wi‑Fi o antenas):
 *  lo que mide la calidad es `precision_m`. */
export type FuenteUbicacion = 'gps' | 'reutilizada' | 'ninguna'

export type PermisoUbicacion = 'granted' | 'denied' | 'prompt'

export type ErrorUbicacion =
  'sin_soporte' | 'contexto_inseguro' | 'permiso_denegado' | 'no_disponible' | 'tiempo_agotado'

/** Una lectura de posición tal como la entrega el navegador. */
export interface Lectura {
  lat: number
  lng: number
  /** Radio de error en metros (68 % de confianza, según la Geolocation API). */
  precision_m: number
  /** Momento en que el sistema tomó la lectura (ISO 8601, UTC). */
  fix_ts: string
}

/** Resultado de `capturarUbicacion`. Nunca lanza: si algo falla, `fuente = 'ninguna'` y `error` dice por qué. */
export interface Ubicacion {
  lat: number | null
  lng: number | null
  precision_m: number | null
  fix_ts: string | null
  fuente: FuenteUbicacion
  permiso: PermisoUbicacion
  duracion_ms: number
  error: ErrorUbicacion | null
}

export type GeoEstado = 'verificada' | 'lejos' | 'imprecisa' | 'sin_referencia' | 'sin_gps'

export interface Referencia {
  lat: number
  lng: number
}

export interface Clasificacion {
  estado: GeoEstado
  /** Distancia a la referencia en metros enteros; `null` si no hay lectura o no hay referencia. */
  distancia_m: number | null
}
