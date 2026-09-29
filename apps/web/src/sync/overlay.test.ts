import { describe, expect, it } from 'vitest'
import type { DoctorRow, OutboxRow, VisitRow } from '../db/db'
import { overlay } from './overlay'

const LINE = 'line-gastru'
const doctor: DoctorRow = {
  id: 'd1',
  full_name: 'Dra. Laura Méndez',
  specialty: null,
  institution_id: 'i1',
  review_state: 'approved',
  default_line_id: LINE,
}
const visit: VisitRow = {
  id: 'v1',
  doctor_id: 'd1',
  institution_id: 'i1',
  primary_line_id: LINE,
  line_ids: [LINE],
  scheduled_at: '2026-09-29T15:30:00Z',
  status: 'scheduled',
  planned_by: 'rep',
  not_done_reason: null,
  updated_at: '2026-09-29T12:00:00Z',
}

let seq = 0
const ev = (type: string, payload: Record<string, unknown>, over: Partial<OutboxRow> = {}): OutboxRow => ({
  seq: ++seq,
  event_id: `e${seq}`,
  type,
  visit_id: null,
  device_ts: '2026-09-29T13:00:00Z',
  payload,
  status: 'pending',
  attempts: 0,
  created_at: '2026-09-29T13:00:00Z',
  ...over,
})

const empty = { visits: [], doctors: [], institutions: [] }

describe('overlay: foto del servidor + eventos pendientes', () => {
  it('un médico y una visita creados sin red aparecen de inmediato', () => {
    const view = overlay(empty, [
      ev('doctor_created', {
        doctor_id: 'd9',
        full_name: 'Dr. Nuevo',
        default_line_id: LINE,
        institution: { id: 'i9', name: 'Clínica Norte' },
      }),
      ev(
        'visit_scheduled',
        { doctor_id: 'd9', line_ids: [LINE], scheduled_at: '2026-09-29T16:00:00Z' },
        { visit_id: 'v9' },
      ),
    ])
    expect(view.doctors.get('d9')?.review_state).toBe('pending_review')
    expect(view.institutions.get('i9')?.name).toBe('Clínica Norte')
    const v = view.visits.get('v9')!
    expect(v.institution_id).toBe('i9')
    expect(v.status).toBe('scheduled')
    expect(v.primary_line_id).toBe(LINE)
  })

  it('reprogramar y marcar «no se realizó» se ven encima de la foto', () => {
    const base = { visits: [visit], doctors: [doctor], institutions: [] }
    const view = overlay(base, [ev('visit_rescheduled', { scheduled_at: '2026-09-29T18:00:00Z' }, { visit_id: 'v1' })])
    expect(view.visits.get('v1')?.scheduled_at).toBe('2026-09-29T18:00:00Z')

    const cancelled = overlay(base, [ev('visit_not_done', { reason: 'doctor_unavailable' }, { visit_id: 'v1' })])
    expect(cancelled.visits.get('v1')).toMatchObject({
      status: 'not_done',
      not_done_reason: 'doctor_unavailable',
    })
  })

  it('no reprograma una visita que ya no está agendada', () => {
    const done = { ...visit, status: 'not_done' as const }
    const view = overlay({ visits: [done], doctors: [doctor], institutions: [] }, [
      ev('visit_rescheduled', { scheduled_at: '2026-09-29T18:00:00Z' }, { visit_id: 'v1' }),
    ])
    expect(view.visits.get('v1')?.scheduled_at).toBe(visit.scheduled_at)
  })

  it('los eventos rechazados o vencidos no se muestran; los confirmados sí (hasta la siguiente bajada)', () => {
    const base = { visits: [visit], doctors: [doctor], institutions: [] }
    const payload = { scheduled_at: '2026-09-29T18:00:00Z' }
    for (const status of ['rejected', 'expired'] as const) {
      const v = overlay(base, [ev('visit_rescheduled', payload, { visit_id: 'v1', status })])
      expect(v.visits.get('v1')?.scheduled_at).toBe(visit.scheduled_at)
    }
    const confirmed = overlay(base, [ev('visit_rescheduled', payload, { visit_id: 'v1', status: 'confirmed' })])
    expect(confirmed.visits.get('v1')?.scheduled_at).toBe('2026-09-29T18:00:00Z')
  })

  it('es idempotente: aplicar un evento sobre una foto que ya lo incluye no cambia nada', () => {
    const created = ev(
      'visit_scheduled',
      { doctor_id: 'd1', line_ids: [LINE], scheduled_at: visit.scheduled_at },
      { visit_id: 'v1', status: 'confirmed' },
    )
    const view = overlay({ visits: [visit], doctors: [doctor], institutions: [] }, [created, created])
    expect([...view.visits.values()]).toEqual([visit])
  })

  it('aplica en orden de llegada (seq) aunque la lista venga desordenada', () => {
    const base = { visits: [visit], doctors: [doctor], institutions: [] }
    const first = ev('visit_rescheduled', { scheduled_at: '2026-09-29T17:00:00Z' }, { visit_id: 'v1' })
    const second = ev('visit_rescheduled', { scheduled_at: '2026-09-29T19:00:00Z' }, { visit_id: 'v1' })
    const view = overlay(base, [second, first])
    expect(view.visits.get('v1')?.scheduled_at).toBe('2026-09-29T19:00:00Z')
  })

  it('ignora eventos de tipos desconocidos', () => {
    const view = overlay(empty, [ev('visit_teleported', {})])
    expect(view.visits.size).toBe(0)
  })
})
