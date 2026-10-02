import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/Toast'
import type { VisitRow } from '../../db/db'
import { WeekScreen } from './WeekScreen'

vi.mock('../../lib/useNow', () => ({ useNow: () => new Date('2026-10-02T15:00:00Z') }))
vi.mock('../../components/ProfileLink', () => ({ ProfileLink: () => null }))
vi.mock('../../components/SyncPill', () => ({ SyncPill: () => null }))
vi.mock('./VisitSheet', () => ({ VisitSheet: () => null }))
vi.mock('./useAgenda', () => {
  const sunday: VisitRow = {
    id: 'sunday', doctor_id: 'd1', institution_id: null, primary_line_id: 'l1', line_ids: ['l1'],
    scheduled_at: '2026-10-04T15:00:00Z', status: 'scheduled', planned_by: 'rep',
    not_done_reason: null, updated_at: '2026-10-01T15:00:00Z',
  }
  return {
    NOT_DONE_LABEL: {},
    useAgenda: () => ({
      loading: false, tz: 'America/Bogota', visits: [sunday], doctors: [], institutions: [], lines: [], reports: new Map(),
      byDay: new Map([['2026-10-04', [sunday]]]),
      vm: (visit: VisitRow) => ({ visit, doctor: { full_name: 'Dra. Laura Méndez' }, lines: [], unsent: false }),
    }),
  }
})

describe('Agenda semanal', () => {
  it.each([
    ['2026-10-04', 'Domingo 4'],
    ['2026-02-30', 'Viernes 2Hoy'],
    ['invalida', 'Viernes 2Hoy'],
  ])('abre el día de ?fecha=%s y descarta fechas inválidas', (date, heading) => {
    render(<MemoryRouter initialEntries={[`/agenda?fecha=${date}`]}><ToastProvider><WeekScreen /></ToastProvider></MemoryRouter>)
    expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument()
  })

  it('identifica ambos meses y permite consultar el domingo y navegar a otra semana', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><ToastProvider><WeekScreen /></ToastProvider></MemoryRouter>)
    expect(screen.getByText('Septiembre – octubre 2026')).toBeInTheDocument()
    const week = screen.getByRole('navigation', { name: 'Semana' })
    expect(within(week).getAllByRole('button', { pressed: false })).toHaveLength(6)
    await user.click(within(week).getByRole('button', { name: 'Domingo 4, 1 visita' }))
    expect(screen.getByRole('heading', { name: 'Domingo 4' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Dra. Laura Méndez/ })).toBeInTheDocument()
    await user.click(within(week).getByRole('button', { name: 'Semana siguiente' }))
    expect(screen.getByRole('button', { name: 'Domingo 11, 0 visitas', pressed: true })).toBeInTheDocument()
    expect(screen.getByText('Octubre 2026')).toBeInTheDocument()
    await user.click(within(week).getByRole('button', { name: 'Semana anterior' }))
    expect(screen.getByRole('button', { name: 'Domingo 4, 1 visita', pressed: true })).toBeInTheDocument()
  })
})
