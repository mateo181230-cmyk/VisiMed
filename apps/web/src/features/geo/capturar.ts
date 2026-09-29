/**
 * Captura de ubicación en el toque. Es el ÚNICO archivo de la app que toca la Geolocation API y la
 * consulta de permiso (lo verifica `aislamiento.test.ts`): así el GPS no puede encenderse fuera de
 * Llegué / Terminé (doc 01 §9.7).
 *
 * Decisión del cliente (28 sep 2026): **un toque, una lectura**. No hay ventana de «mejor lectura» ni
 * seguimiento: se pide la posición una vez, con alta precisión y sin reutilizar una guardada
 * (`maximumAge = 0`), y el GPS se apaga solo al responder. La mayoría de visitas son en hospitales
 * urbanos con radio de 300 m, donde una lectura basta para verificar el lugar.
 *
 * La pantalla no espera esta lectura: el toque ya quedó registrado con su hora y la ubicación se
 * adjunta cuando llega (ver `features/visit/registrarToque.ts`).
 */
import type { ErrorUbicacion, Lectura, PermisoUbicacion, Ubicacion } from './tipos'

/** Tope de una lectura. Lo normal son 1–3 s; esto solo acota el peor caso. */
export const TIMEOUT_LECTURA_MS = 8_000
const CONSULTA_PERMISO_MS = 500
const CLAVE_CONCEDIDO = 'uno.ubicacion.concedida'

const PERMISO_DENEGADO = 1
const POSICION_NO_DISPONIBLE = 2

export interface OpcionesCaptura {
  timeoutMs?: number
  /** Solo para pruebas. */
  geo?: Geolocation
  permisos?: Pick<Permissions, 'query'>
}

/** `false` si la página no está en HTTPS (ni `localhost`): ahí el navegador no entrega ubicación. */
export function contextoSeguro(): boolean {
  return typeof window === 'undefined' || window.isSecureContext !== false
}

/** `false` si el navegador no ofrece la API de ubicación. */
export function ubicacionDisponible(): boolean {
  return typeof navigator !== 'undefined' && !!navigator.geolocation
}

export function permisosDisponibles(): boolean {
  return typeof navigator !== 'undefined' && !!navigator.permissions?.query
}

function recordarConcedido(valor: boolean): void {
  try {
    if (valor) localStorage.setItem(CLAVE_CONCEDIDO, '1')
    else localStorage.removeItem(CLAVE_CONCEDIDO)
  } catch {
    // Sin almacenamiento local no hay nada que recordar.
  }
}

function concedidoAntes(): boolean {
  try {
    return localStorage.getItem(CLAVE_CONCEDIDO) === '1'
  } catch {
    return false
  }
}

/** Estado del permiso con la Permissions API. Si el navegador no la tiene, asume `prompt`. */
export async function leerPermiso(permisos?: Pick<Permissions, 'query'>): Promise<PermisoUbicacion> {
  const api = permisos ?? (typeof navigator !== 'undefined' ? navigator.permissions : undefined)
  if (!api) return 'prompt'
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      api.query({ name: 'geolocation' }).then((p) => p.state),
      new Promise<'prompt'>((resolve) => {
        timer = setTimeout(() => resolve('prompt'), CONSULTA_PERMISO_MS)
      }),
    ])
  } catch {
    return 'prompt'
  } finally {
    clearTimeout(timer)
  }
}

/**
 * Estado del permiso para decidir si la app puede usarse. Sin Permissions API (navegadores viejos) se
 * confía en la última vez que una lectura salió bien.
 */
export async function estadoPermiso(): Promise<PermisoUbicacion> {
  if (!permisosDisponibles()) return concedidoAntes() ? 'granted' : 'prompt'
  return leerPermiso()
}

/** Avisa cuando el usuario cambia el permiso desde los ajustes del navegador. Devuelve cómo dejar de escuchar. */
export function observarPermiso(alCambiar: (estado: PermisoUbicacion) => void): () => void {
  if (!permisosDisponibles()) return () => {}
  let cerrado = false
  let estado: PermissionStatus | null = null
  const alEvento = (): void => {
    if (estado && !cerrado) alCambiar(estado.state)
  }
  navigator.permissions
    .query({ name: 'geolocation' })
    .then((p) => {
      if (cerrado) return
      estado = p
      p.addEventListener('change', alEvento)
    })
    .catch(() => {})
  return () => {
    cerrado = true
    estado?.removeEventListener('change', alEvento)
  }
}

function aLectura(pos: GeolocationPosition): Lectura | null {
  const { latitude, longitude, accuracy } = pos.coords
  if (![latitude, longitude, accuracy].every(Number.isFinite)) return null
  return {
    lat: latitude,
    lng: longitude,
    precision_m: accuracy,
    fix_ts: new Date(pos.timestamp).toISOString(),
  }
}

type Respuesta = { lectura: Lectura | null; codigoError: number | null }

function pedirLectura(geo: Geolocation, timeoutMs: number): Promise<Respuesta> {
  return new Promise((resolve) => {
    let hecho = false
    const terminar = (r: Respuesta): void => {
      if (hecho) return
      hecho = true
      clearTimeout(seguro)
      resolve(r)
    }
    // Algunos navegadores no aplican `timeout` mientras hay un aviso de permiso abierto: este tope lo garantiza.
    const seguro = setTimeout(() => terminar({ lectura: null, codigoError: null }), timeoutMs)
    geo.getCurrentPosition(
      (pos) => terminar({ lectura: aLectura(pos), codigoError: null }),
      (err) => terminar({ lectura: null, codigoError: err.code }),
      { enableHighAccuracy: true, maximumAge: 0, timeout: timeoutMs },
    )
  })
}

/** Toma UNA lectura de la ubicación. Nunca lanza ni se cuelga: el peor caso devuelve `fuente = 'ninguna'`. */
export async function capturarUbicacion(opciones: OpcionesCaptura = {}): Promise<Ubicacion> {
  const inicio = Date.now()
  const timeoutMs = opciones.timeoutMs ?? TIMEOUT_LECTURA_MS

  const ninguna = (error: ErrorUbicacion, permiso: PermisoUbicacion): Ubicacion => ({
    lat: null,
    lng: null,
    precision_m: null,
    fix_ts: null,
    fuente: 'ninguna',
    permiso,
    duracion_ms: Date.now() - inicio,
    error,
  })

  const geo = opciones.geo ?? (typeof navigator !== 'undefined' ? navigator.geolocation : undefined)
  if (!geo) return ninguna('sin_soporte', 'prompt')
  // Fuera de HTTPS (o localhost) el navegador responde «permiso denegado»; aquí se distingue para el diagnóstico.
  if (!contextoSeguro()) return ninguna('contexto_inseguro', 'prompt')

  const permiso = await leerPermiso(opciones.permisos)
  if (permiso === 'denied') {
    recordarConcedido(false)
    return ninguna('permiso_denegado', 'denied')
  }

  const { lectura, codigoError } = await pedirLectura(geo, timeoutMs)
  if (lectura) {
    recordarConcedido(true)
    return { ...lectura, fuente: 'gps', permiso: 'granted', duracion_ms: Date.now() - inicio, error: null }
  }
  if (codigoError === PERMISO_DENEGADO) {
    recordarConcedido(false)
    return ninguna('permiso_denegado', 'denied')
  }
  return ninguna(codigoError === POSICION_NO_DISPONIBLE ? 'no_disponible' : 'tiempo_agotado', permiso)
}
