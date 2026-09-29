import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { ToastProvider } from '../../components/Toast'
import { type GeoResult, type InstitutionRow, type VisitRow, db } from '../../db/db'
import type { TouchMoment } from '../../sync/events'
import type { VisitVM } from '../agenda/useAgenda'
import { TouchSummary, VisitActions } from './VisitActions'

const TZ = 'America/Bogota'
const hospital: InstitutionRow = {
  id: 'i1',
  name: 'Hospital San Rafael',
  address: null,
  city: null,
  lat: 4.6765,
  lng: -74.0481,
  radius_m: 300,
}
const ago = (ms: number): string => new Date(Date.now() - ms).toISOString()
const geo = (
  state: GeoResult['state'],
  distance_m: number | null = null,
  precision_m: number | null = 15,
): GeoResult => ({
  state,
  distance_m,
  precision_m,
})

function vmOf(over: Partial<VisitRow> = {}, capturing: TouchMoment | null = null): VisitVM {
  const visit: VisitRow = {
    id: 'v1',
    doctor_id: 'd1',
    institution_id: 'i1',
    primary_line_id: 'l1',
    line_ids: ['l1'],
    scheduled_at: new Date().toISOString(),
    status: 'scheduled',
    planned_by: 'rep',
    not_done_reason: null,
    updated_at: new Date().toISOString(),
    ...over,
  }
  return { visit, doctor: undefined, institution: hospital, lines: [], unsent: false, capturing }
}

const renderActions = (vm: VisitVM) =>
  render(
    <ToastProvider>
      <VisitActions vm={vm} tz={TZ} />
    </ToastProvider>,
  )

beforeEach(async () => {
  await db.outbox.clear()
})

describe('Llegué', () => {
  it('una visita de hoy tiene un solo botón grande «Llegué»', () => {
    renderActions(vmOf())
    expect(screen.getByRole('button', { name: 'Llegué' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Terminé' })).not.toBeInTheDocument()
  })

  it('un toque registra la llegada al instante y avisa cómo quedó la ubicación', async () => {
    const user = userEvent.setup()
    renderActions(vmOf())
    await user.click(screen.getByRole('button', { name: 'Llegué' }))

    // En jsdom no hay GPS: el toque debe registrarse igual, sin ubicación, y no perderse.
    await waitFor(async () => expect(await db.outbox.count()).toBe(1))
    const [row] = await db.outbox.toArray()
    expect(row).toMatchObject({ type: 'visit_arrived', visit_id: 'v1' })
    expect(await screen.findByText(/Llegada registrada · ○ Sin GPS/)).toBeInTheDocument()
    await waitFor(async () => expect((await db.outbox.toArray())[0]!.status).toBe('pending'))
  })

  it('una visita agendada para otro día no ofrece «Llegué»', () => {
    renderActions(vmOf({ scheduled_at: new Date(Date.now() + 3 * 86_400_000).toISOString() }))
    expect(screen.queryByRole('button', { name: 'Llegué' })).not.toBeInTheDocument()
  })
})

describe('En visita y Terminé', () => {
  const enVisita = (over: Partial<VisitRow> = {}, capturing: TouchMoment | null = null) =>
    vmOf({ status: 'in_progress', arrived_at: ago(5_000), arrival_geo: geo('verificada', 90), ...over }, capturing)

  it('muestra el cronómetro, la ubicación verificada y «Terminé»', () => {
    renderActions(enVisita())
    expect(screen.getByRole('timer')).toHaveTextContent(/^00:0\d$/)
    expect(screen.getByText('✓ Ubicación verificada')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Terminé' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Llegué' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reintentar ubicación' })).not.toBeInTheDocument()
  })

  it('«lejos» muestra la distancia y la visita sigue en curso (no se bloquea nada)', () => {
    renderActions(enVisita({ arrival_geo: geo('lejos', 850) }))
    expect(screen.getByText('⚠ A 850 m del consultorio')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Terminé' })).toBeEnabled()
  })

  it('un toque en «Terminé» registra la salida', async () => {
    const user = userEvent.setup()
    renderActions(enVisita())
    await user.click(screen.getByRole('button', { name: 'Terminé' }))
    await waitFor(async () => expect(await db.outbox.count()).toBe(1))
    expect((await db.outbox.toArray())[0]).toMatchObject({ type: 'visit_finished', visit_id: 'v1' })
    expect(await screen.findByText(/Visita terminada/)).toBeInTheDocument()
  })

  it.each([['sin_gps'], ['imprecisa']] as const)('con ubicación «%s» y dentro de 2 min ofrece reintentar', (estado) => {
    renderActions(enVisita({ arrival_geo: geo(estado, null, estado === 'imprecisa' ? 400 : null) }))
    expect(screen.getByRole('button', { name: 'Reintentar ubicación' })).toBeInTheDocument()
  })

  it('pasados 2 min ya no ofrece reintentar', () => {
    renderActions(enVisita({ arrived_at: ago(10 * 60_000), arrival_geo: geo('sin_gps', null, null) }))
    expect(screen.queryByRole('button', { name: 'Reintentar ubicación' })).not.toBeInTheDocument()
    expect(screen.getByText('○ Sin GPS · Reintentar')).toBeInTheDocument()
  })

  it('mientras busca la ubicación lo dice (y no muestra «Sin GPS» todavía)', () => {
    renderActions(enVisita({ arrival_geo: geo('sin_gps', null, null) }, 'arrival'))
    expect(screen.getByText('Buscando tu ubicación…')).toBeInTheDocument()
    expect(screen.queryByText(/Sin GPS/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reintentar ubicación' })).not.toBeInTheDocument()
  })

  it('reintentar sin lograr lectura avisa y NO envía nada', async () => {
    const user = userEvent.setup()
    renderActions(enVisita({ arrival_geo: geo('sin_gps', null, null) }))
    await user.click(screen.getByRole('button', { name: 'Reintentar ubicación' }))
    expect(await screen.findByText('No pudimos tomar tu ubicación. Intenta de nuevo.')).toBeInTheDocument()
    expect(await db.outbox.count()).toBe(0)
  })
})

describe('resumen de una visita terminada', () => {
  const renderSummary = (vm: VisitVM) =>
    render(
      <ToastProvider>
        <TouchSummary vm={vm} />
      </ToastProvider>,
    )

  it('muestra la duración y cómo quedó la ubicación de la llegada y de la salida', () => {
    renderSummary(
      vmOf({
        status: 'finished',
        arrived_at: ago(30 * 60_000),
        finished_at: ago(6 * 60_000),
        arrival_geo: geo('verificada', 60),
        finish_geo: geo('lejos', 900),
      }),
    )
    expect(screen.getByText('24 min')).toBeInTheDocument()
    expect(screen.getByText(/Llegada/)).toBeInTheDocument()
    expect(screen.getByText('✓ Ubicación verificada')).toBeInTheDocument()
    expect(screen.getByText(/Salida/)).toBeInTheDocument()
    expect(screen.getByText('⚠ A 900 m del consultorio')).toBeInTheDocument()
  })

  it('avisa cuando se tocó Terminé sin Llegué', () => {
    renderSummary(vmOf({ status: 'finished', finished_at: ago(60_000), finish_geo: geo('verificada', 20) }))
    expect(screen.getByText(/se tocó Terminé sin Llegué/)).toBeInTheDocument()
  })

  it('una visita que nunca empezó no muestra resumen', () => {
    renderSummary(vmOf({ status: 'not_done' }))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByText(/Duración|Llegada|Salida/)).not.toBeInTheDocument()
  })
})
