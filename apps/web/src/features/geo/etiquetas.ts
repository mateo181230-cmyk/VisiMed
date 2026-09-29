import type { GeoResult } from '../../db/db'
import type { ErrorUbicacion, GeoEstado, PermisoUbicacion, Referencia } from './tipos'

/** «850 m», «1,2 km». */
export function formatearDistancia(metros: number): string {
  if (metros < 1000) return `${Math.round(metros)} m`
  return `${(metros / 1000).toLocaleString('es-CO', { maximumFractionDigits: 1 })} km`
}

export type TonoGeo = 'ok' | 'warn' | 'info'

/** Texto y tono que ve el visitador según el estado de la geocerca (doc 01 §9.3). */
export function etiquetaEstado(
  estado: GeoEstado,
  detalle: { distancia_m: number | null; precision_m: number | null },
): { texto: string; tono: TonoGeo } {
  switch (estado) {
    case 'verificada':
      return { texto: '✓ Ubicación verificada', tono: 'ok' }
    case 'lejos':
      return {
        texto: `⚠ A ${formatearDistancia(detalle.distancia_m ?? 0)} del consultorio`,
        tono: 'warn',
      }
    case 'imprecisa':
      return {
        texto: `○ Ubicación imprecisa (± ${Math.round(detalle.precision_m ?? 0)} m)`,
        tono: 'info',
      }
    case 'sin_referencia':
      return { texto: '○ Ubicación registrada', tono: 'info' }
    case 'sin_gps':
      return { texto: '○ Sin GPS · Reintentar', tono: 'info' }
  }
}

/** Igual que `etiquetaEstado`, a partir de cómo quedó guardada la ubicación de un toque. */
export function etiquetaGeo(geo: GeoResult): { texto: string; tono: TonoGeo } {
  return etiquetaEstado(geo.state, { distancia_m: geo.distance_m, precision_m: geo.precision_m })
}

export const TEXTO_PERMISO: Record<PermisoUbicacion, string> = {
  granted: 'Concedido',
  denied: 'Negado',
  prompt: 'Aún no se ha pedido',
}

export const TEXTO_ERROR: Record<ErrorUbicacion, string> = {
  sin_soporte: 'Este navegador no ofrece ubicación.',
  contexto_inseguro: 'La página no está en HTTPS: el navegador bloquea la ubicación.',
  permiso_denegado: 'El permiso de ubicación está negado. Se activa en los ajustes del navegador o del teléfono.',
  no_disponible: 'El teléfono no pudo determinar su posición (¿tiene la ubicación apagada?).',
  tiempo_agotado: 'No llegó ninguna lectura a tiempo.',
}

/**
 * Lee coordenadas pegadas desde Google Maps («4.67650, -74.04810»). Solo punto decimal; separa por coma,
 * punto y coma o espacios. Devuelve `null` si no son coordenadas válidas.
 */
export function leerCoordenadas(texto: string): Referencia | null {
  const m = /^\s*\(?\s*(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*\)?\s*$/.exec(texto)
  if (!m) return null
  const lat = Number(m[1])
  const lng = Number(m[2])
  if (Math.abs(lat) > 90 || Math.abs(lng) > 180) return null
  return { lat, lng }
}
