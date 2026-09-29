import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { ToastProvider } from '../../components/Toast'
import { type DoctorRow, type OutboxRow, type ReportRow, type VisitRow, db } from '../../db/db'
import { overlay } from '../../sync/overlay'
import type { Agenda, VisitVM } from '../agenda/useAgenda'
import { displayValue, dueDateLabel, reportSnippet } from './labels'
import { ReportSheet } from './ReportSheet'
import { type HistoryItem, countToConfirm, groupHistory } from './useHistory'

const TZ = 'America/Bogota'
const LINE = 'l-gastru'
const doctor: DoctorRow = {
  id: 'd1',
  full_name: 'Dra. Laura Méndez',
  specialty: 'Medicina Interna',
  institution_id: null,
  review_state: 'approved',
  default_line_id: LINE,
}

function visit(id: string, over: Partial<VisitRow> = {}): VisitRow {
  return {
    id,
    doctor_id: 'd1',
    institution_id: null,
    primary_line_id: LINE,
    line_ids: [LINE],
    scheduled_at: '2026-09-29T15:00:00Z',
    status: 'ready',
    planned_by: 'rep',
    not_done_reason: null,
    updated_at: '2026-09-29T16:00:00Z',
    finished_at: '2026-09-29T15:20:00Z',
    arrived_at: '2026-09-29T15:05:00Z',
    ...over,
  }
}

function report(visitId: string, over: Partial<ReportRow> = {}): ReportRow {
  return {
    visit_id: visitId,
    status: 'ready',
    complete: true,
    confirmed_at: null,
    updated_at: '2026-09-29T15:30:00Z',
    fields: {
      interest_level: { value: 4, confidence: 'high', source: 'call' },
      visit_outcome: { value: 'follow_up_set', confidence: 'high', source: 'call' },
      order_taken: { value: false, confidence: 'medium', source: 'call' },
      no_order_reason: { value: 'no_need_to_switch', confidence: 'low', source: 'call' },
      competitor: { value: 'pantoprazol', confidence: 'high', source: 'call' },
      next_action: { value: 'Llevarle muestras', confidence: 'high', source: 'call' },
      next_action_due: { value: '2026-10-13', confidence: 'high', source: 'call' },
      summary: { value: 'Interés 4/5; sin pedido porque ya usa pantoprazol.', confidence: 'high', source: 'call' },
    },
    ...over,
  }
}

function agendaOf(visits: VisitRow[], reports: ReportRow[] = []): Agenda {
  const byVisit = new Map(reports.map((r) => [r.visit_id, r]))
  return {
    loading: false,
    tz: TZ,
    lines: [],
    doctors: [doctor],
    institutions: [],
    visits,
    byDay: new Map(),
    reports: byVisit,
    vm: (v): VisitVM => ({ visit: v, doctor, institution: undefined, lines: [], unsent: false, capturing: null }),
  }
}

// «Hoy» = 29 sep 2026, 10:00 en Bogotá
const NOW = new Date('2026-09-29T15:00:00Z')

describe('Historial: agrupar por día', () => {
  it('agrupa por día local, lo más reciente primero, con «Hoy» y «Ayer»', () => {
    const groups = groupHistory(
      agendaOf([
        visit('a', { finished_at: '2026-09-29T14:00:00Z' }),
        visit('b', { finished_at: '2026-09-29T14:40:00Z' }),
        visit('c', { finished_at: '2026-09-28T20:00:00Z', scheduled_at: '2026-09-28T19:00:00Z' }),
        visit('d', { finished_at: '2026-09-20T20:00:00Z', scheduled_at: '2026-09-20T19:00:00Z' }),
      ]),
      NOW,
    )
    expect(groups.map((g) => g.title)).toEqual(['Hoy', 'Ayer', 'Domingo, 20 de septiembre'])
    expect(groups[0]!.items.map((i) => i.vm.visit.id)).toEqual(['b', 'a']) // la última primero
  })

  it('usa el día local de Bogotá, no el de UTC (una visita de las 8 p. m. no salta de día)', () => {
    const groups = groupHistory(agendaOf([visit('x', { finished_at: '2026-09-30T01:30:00Z' })]), NOW)
    expect(groups[0]!.day).toBe('2026-09-29') // 8:30 p. m. del 29 en Bogotá
  })

  it('solo entran las visitas que ya ocurrieron; las agendadas y en curso no', () => {
    const groups = groupHistory(
      agendaOf([visit('a'), visit('b', { status: 'scheduled' }), visit('c', { status: 'in_progress' })]),
      NOW,
    )
    expect(groups.flatMap((g) => g.items.map((i) => i.vm.visit.id))).toEqual(['a'])
  })

  it('cada visita lleva su ficha, y se cuentan las que esperan confirmación', () => {
    const groups = groupHistory(
      agendaOf(
        [visit('a'), visit('b', { status: 'confirmed' }), visit('c', { status: 'finished' })],
        [report('a'), report('b', { status: 'confirmed' })],
      ),
      NOW,
    )
    const items = groups.flatMap((g) => g.items)
    expect(items.find((i) => i.vm.visit.id === 'c')!.report).toBeNull()
    expect(countToConfirm(groups)).toBe(1)
  })
})

describe('Historial: textos', () => {
  it('traduce los valores del servidor', () => {
    expect(displayValue('interest_level', 4)).toBe('4 de 5')
    expect(displayValue('visit_outcome', 'order_taken')).toBe('Hizo un pedido')
    expect(displayValue('order_taken', false)).toBe('No')
    expect(displayValue('no_order_reason', 'competitor_better')).toBe('La competencia está mejor')
    expect(displayValue('objection', '')).toBeNull()
    expect(displayValue('objection', null)).toBeNull()
  })

  it('el resumen de la lista es el de la llamada o, si falta, lo esencial', () => {
    expect(reportSnippet(report('a'))).toMatch(/^Interés 4\/5/)
    const noSummary = report('a')
    delete noSummary.fields.summary
    expect(reportSnippet(noSummary)).toBe('4 de 5 · Quedó un seguimiento')
  })

  it('la fecha del próximo paso sale en español', () => {
    expect(dueDateLabel(report('a'))).toBe('Martes, 13 de octubre')
    expect(dueDateLabel(report('a', { fields: {} }))).toBeNull()
  })
})

describe('Vista optimista de la ficha (funciona sin red)', () => {
  const ev = (type: string, payload: Record<string, unknown>, status: OutboxRow['status'] = 'pending'): OutboxRow => ({
    seq: Math.floor(Math.random() * 1e6),
    event_id: crypto.randomUUID(),
    type,
    visit_id: 'v1',
    device_ts: '2026-09-29T16:00:00Z',
    payload,
    status,
    attempts: 0,
    created_at: '2026-09-29T16:00:00Z',
  })
  const base = { visits: [visit('v1')], doctors: [doctor], institutions: [], reports: [report('v1')] }

  it('una corrección se ve al instante y queda como del visitador', () => {
    const view = overlay(base, [ev('report_field_edited', { field: 'interest_level', value: 2 })])
    expect(view.reports.get('v1')!.fields.interest_level).toEqual({ value: 2, confidence: 'high', source: 'rep_edit' })
    expect(view.reports.get('v1')!.fields.competitor!.source).toBe('call') // lo demás no cambia
  })

  it('texto vacío borra el campo y el texto se recorta', () => {
    const view = overlay(base, [
      ev('report_field_edited', { field: 'competitor', value: '   ' }),
      ev('report_field_edited', { field: 'objection', value: '  Dice que es caro  ' }),
    ])
    expect(view.reports.get('v1')!.fields.competitor!.value).toBeNull()
    expect(view.reports.get('v1')!.fields.objection!.value).toBe('Dice que es caro')
  })

  it('confirmar marca la ficha y la visita, y aplicarlo dos veces da lo mismo', () => {
    const confirm = ev('report_confirmed', {})
    const once = overlay(base, [confirm])
    const twice = overlay({ ...base, reports: [...once.reports.values()], visits: [...once.visits.values()] }, [confirm])
    expect(once.reports.get('v1')!.status).toBe('confirmed')
    expect(once.visits.get('v1')!.status).toBe('confirmed')
    expect(twice.reports.get('v1')).toEqual(once.reports.get('v1'))
  })

  it('un evento rechazado o de una visita sin ficha no cambia nada', () => {
    const view = overlay(base, [
      ev('report_confirmed', {}, 'rejected'),
      { ...ev('report_confirmed', {}), visit_id: 'otra' },
    ])
    expect(view.reports.get('v1')!.status).toBe('ready')
  })
})

describe('Hoja de la ficha', () => {
  beforeEach(async () => {
    await db.outbox.clear()
  })

  function open(item: HistoryItem) {
    const onClose = () => {}
    render(
      <ToastProvider>
        <ReportSheet item={item} tz={TZ} onClose={onClose} />
      </ToastProvider>,
    )
    return userEvent.setup()
  }

  const item = (over: Partial<HistoryItem> = {}): HistoryItem => ({
    vm: agendaOf([visit('v1')]).vm(visit('v1')),
    report: report('v1'),
    at: '2026-09-29T15:20:00Z',
    ...over,
  })

  it('muestra los datos y marca como «Revisar» los dudosos', () => {
    open(item())
    expect(screen.getByText('4 de 5')).toBeInTheDocument()
    expect(screen.getByText('Quedó un seguimiento')).toBeInTheDocument()
    expect(screen.getByText('No necesita cambiar lo que usa')).toBeInTheDocument()
    expect(screen.getByText('Revisar')).toBeInTheDocument() // el motivo llegó con confianza baja
    expect(screen.getByText('Martes, 13 de octubre')).toBeInTheDocument()
  })

  it('confirmar es un toque y queda en la cola', async () => {
    const user = open(item())
    await user.click(screen.getByRole('button', { name: /Confirmar/ }))
    await waitFor(async () => expect(await db.outbox.count()).toBe(1))
    const [event] = await db.outbox.toArray()
    expect(event).toMatchObject({ type: 'report_confirmed', visit_id: 'v1', status: 'pending' })
  })

  it('corregir el interés son dos toques: el dato y el número', async () => {
    const user = open(item())
    await user.click(screen.getByRole('button', { name: /^Interés: 4 de 5/ }))
    await user.click(screen.getByRole('button', { name: '2' }))
    await waitFor(async () => expect(await db.outbox.count()).toBe(1))
    expect((await db.outbox.toArray())[0]).toMatchObject({
      type: 'report_field_edited',
      payload: { field: 'interest_level', value: 2 },
    })
  })

  it('decir que sí hubo pedido también deja el motivo en «Hubo pedido»', async () => {
    const user = open(item())
    await user.click(screen.getByRole('button', { name: /^¿Hubo pedido\?/ }))
    await user.click(screen.getByRole('button', { name: 'Sí' }))
    await waitFor(async () => expect(await db.outbox.count()).toBe(2))
    const events = await db.outbox.orderBy('seq').toArray()
    expect(events.map((e) => e.payload)).toEqual([
      { field: 'order_taken', value: true },
      { field: 'no_order_reason', value: 'not_applicable' },
    ])
  })

  it('un texto se corrige y también se puede borrar', async () => {
    const user = open(item())
    await user.click(screen.getByRole('button', { name: /^Competencia:/ }))
    const box = screen.getByRole('textbox', { name: 'Nuevo valor' })
    await user.clear(box)
    await user.type(box, 'omeprazol')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(async () => expect(await db.outbox.count()).toBe(1))
    expect((await db.outbox.toArray())[0]!.payload).toEqual({ field: 'competitor', value: 'omeprazol' })
  })

  it('ya confirmada no ofrece «Confirmar» pero sigue permitiendo corregir', () => {
    open(item({ report: report('v1', { status: 'confirmed' }) }))
    expect(screen.queryByRole('button', { name: /Confirmar/ })).not.toBeInTheDocument()
    expect(screen.getByText(/Resumen confirmado/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Competencia:/ })).toBeInTheDocument()
  })

  it('sin ficha explica qué pasa: te llamamos de nuevo a las…', () => {
    const v = visit('v2', {
      status: 'finished',
      call: { status: 'queued', attempt: 1, next_at: '2026-09-29T15:20:00Z', reason: 'no-answer' },
    })
    open({ vm: agendaOf([v]).vm(v), report: null, at: v.finished_at! })
    expect(screen.getByText(/No contestaste\. Te llamamos de nuevo a las 10:20 AM/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Confirmar/ })).not.toBeInTheDocument()
  })
})
