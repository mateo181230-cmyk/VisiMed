import { describe, expect, it } from 'vitest'
import { formatDuration, formatElapsed } from './format'

describe('formatElapsed (cronómetro de la visita)', () => {
  it.each([
    [0, '00:00'],
    [5_000, '00:05'],
    [754_000, '12:34'],
    [3_599_000, '59:59'],
    [3_725_000, '1:02:05'],
    [-1_000, '00:00'],
  ])('%i ms → %s', (ms, esperado) => {
    expect(formatElapsed(ms)).toBe(esperado)
  })
})

describe('formatDuration (avisos)', () => {
  it.each([
    [20_000, 'menos de 1 min'],
    [24 * 60_000 + 10_000, '24 min'],
    [65 * 60_000, '1 h 05 min'],
    [120 * 60_000, '2 h 00 min'],
  ])('%i ms → %s', (ms, esperado) => {
    expect(formatDuration(ms)).toBe(esperado)
  })
})
