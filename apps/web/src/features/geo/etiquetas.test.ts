import { describe, expect, it } from 'vitest'
import { etiquetaEstado, formatearDistancia, leerCoordenadas } from './etiquetas'

describe('formatearDistancia', () => {
  it('metros por debajo de 1 km y kilómetros con coma decimal', () => {
    expect(formatearDistancia(850)).toBe('850 m')
    expect(formatearDistancia(999.6)).toBe('1000 m')
    expect(formatearDistancia(1200)).toBe('1,2 km')
  })
})

describe('etiquetaEstado (doc 01 §9.3)', () => {
  it('usa los textos del visitador', () => {
    const sin = { distancia_m: null, precision_m: null }
    expect(etiquetaEstado('verificada', sin)).toEqual({
      texto: '✓ Ubicación verificada',
      tono: 'ok',
    })
    expect(etiquetaEstado('lejos', { distancia_m: 850, precision_m: 15 })).toEqual({
      texto: '⚠ A 850 m del consultorio',
      tono: 'warn',
    })
    expect(etiquetaEstado('imprecisa', { distancia_m: null, precision_m: 300 }).texto).toBe(
      '○ Ubicación imprecisa (± 300 m)',
    )
    expect(etiquetaEstado('sin_referencia', sin).tono).toBe('info')
    expect(etiquetaEstado('sin_gps', sin).texto).toContain('Reintentar')
  })
})

describe('leerCoordenadas (pegadas desde Google Maps)', () => {
  it.each([
    ['4.67650, -74.04810', { lat: 4.6765, lng: -74.0481 }],
    ['4.6765,-74.0481', { lat: 4.6765, lng: -74.0481 }],
    ['  4.6765 -74.0481 ', { lat: 4.6765, lng: -74.0481 }],
    ['(4.6765, -74.0481)', { lat: 4.6765, lng: -74.0481 }],
    ['-12.05, 77', { lat: -12.05, lng: 77 }],
  ])('%s', (texto, esperado) => {
    expect(leerCoordenadas(texto)).toEqual(esperado)
  })

  it.each(['', 'hola', '4.6765', '95, 10', '10, 190', '4,6765, -74,0481 x'])('rechaza «%s»', (texto) => {
    expect(leerCoordenadas(texto)).toBeNull()
  })
})
