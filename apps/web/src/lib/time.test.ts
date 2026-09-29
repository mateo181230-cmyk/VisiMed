import { describe, expect, it } from 'vitest'
import {
  addDays,
  dateKey,
  dayLetter,
  formatLongDate,
  formatTime,
  hhmm,
  localToUtc,
  suggestedSlots,
  tzOffsetMinutes,
  weekStart,
} from './time'

const BOG = 'America/Bogota'

describe('zona horaria de Bogotá (UTC−5, sin horario de verano)', () => {
  it('calcula el desfase', () => {
    expect(tzOffsetMinutes(new Date('2026-09-29T12:00:00Z'), BOG)).toBe(-300)
  })

  it('una visita a las 23:30 de Colombia cae en el día correcto', () => {
    expect(dateKey('2026-09-30T04:30:00Z', BOG)).toBe('2026-09-29')
    expect(dateKey('2026-09-30T05:00:00Z', BOG)).toBe('2026-09-30')
  })

  it('convierte hora local a UTC y de vuelta', () => {
    const utc = localToUtc('2026-09-29', '10:30', BOG)
    expect(utc.toISOString()).toBe('2026-09-29T15:30:00.000Z')
    expect(hhmm(utc, BOG)).toBe('10:30')
    expect(localToUtc('2026-09-29', '23:30', BOG).toISOString()).toBe('2026-09-30T04:30:00.000Z')
  })

  it('da formato de 12 horas como la maqueta', () => {
    expect(formatTime('2026-09-29T15:30:00Z', BOG)).toBe('10:30 AM')
    expect(formatTime('2026-09-29T05:05:00Z', BOG)).toBe('12:05 AM')
    expect(formatTime('2026-09-29T17:00:00Z', BOG)).toBe('12:00 PM')
    expect(formatTime('2026-09-29T20:15:00Z', BOG)).toBe('3:15 PM')
  })
})

describe('zonas con horario de verano', () => {
  const NY = 'America/New_York'
  it('respeta el cambio de hora', () => {
    expect(tzOffsetMinutes(new Date('2026-01-15T12:00:00Z'), NY)).toBe(-300)
    expect(tzOffsetMinutes(new Date('2026-07-15T12:00:00Z'), NY)).toBe(-240)
    // 8 de marzo de 2026: a las 2:00 se adelanta el reloj; 3:30 ya es UTC−4.
    expect(localToUtc('2026-03-08', '03:30', NY).toISOString()).toBe('2026-03-08T07:30:00.000Z')
    expect(localToUtc('2026-03-07', '03:30', NY).toISOString()).toBe('2026-03-07T08:30:00.000Z')
  })
})

describe('días y semanas', () => {
  it('formatea fechas en español', () => {
    expect(formatLongDate('2026-09-29')).toBe('Martes, 29 de septiembre')
    expect(formatLongDate('2026-04-22')).toBe('Miércoles, 22 de abril')
  })

  it('suma días entre meses y años', () => {
    expect(addDays('2026-09-29', 2)).toBe('2026-10-01')
    expect(addDays('2026-01-01', -1)).toBe('2025-12-31')
    expect(addDays('2028-02-28', 1)).toBe('2028-02-29')
  })

  it('la semana empieza el lunes', () => {
    expect(weekStart('2026-09-29')).toBe('2026-09-28') // martes
    expect(weekStart('2026-09-28')).toBe('2026-09-28') // lunes
    expect(weekStart('2026-10-04')).toBe('2026-09-28') // domingo
  })

  it('letras del día', () => {
    expect(['2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02', '2026-10-03'].map(dayLetter)).toEqual([
      'L',
      'M',
      'M',
      'J',
      'V',
      'S',
    ])
  })
})

describe('horas sugeridas', () => {
  const now = new Date('2026-09-29T15:10:00Z') // 10:10 en Bogotá
  it('hoy empieza en la próxima media hora', () => {
    expect(suggestedSlots('2026-09-29', BOG, now, 3)).toEqual(['10:30', '11:00', '11:30'])
  })
  it('a una hora exacta salta a la siguiente media hora', () => {
    expect(suggestedSlots('2026-09-29', BOG, new Date('2026-09-29T15:30:00Z'), 2)).toEqual(['11:00', '11:30'])
  })
  it('otro día empieza a las 8:00', () => {
    expect(suggestedSlots('2026-09-30', BOG, now, 3)).toEqual(['08:00', '08:30', '09:00'])
  })
  it('no sugiere horas de madrugada', () => {
    expect(suggestedSlots('2026-09-29', BOG, new Date('2026-09-29T08:00:00Z'), 2)[0]).toBe('07:00')
  })
})
