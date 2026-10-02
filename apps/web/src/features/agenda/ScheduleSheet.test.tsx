import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/Toast'
import { db } from '../../db/db'
import type { DoctorRow, InstitutionRow, LineRow, VisitRow } from '../../db/db'
import { ScheduleSheet } from './ScheduleSheet'
import type { Agenda } from './useAgenda'

const TZ = 'America/Bogota'
const LINES: LineRow[] = [
  { id: 'l-gastru', code: 'GASTRU', name: 'GASTRU', active: true },
  { id: 'l-respi', code: 'RESPI', name: 'RESPI', active: true },
]
const INSTITUTIONS: InstitutionRow[] = [
  { id: 'i-central', name: 'Clínica Central', address: null, city: null, lat: null, lng: null, radius_m: 150 },
]
const DOCTORS: DoctorRow[] = [
  {
    id: 'd-laura',
    full_name: 'Dra. Laura Méndez',
    specialty: 'Medicina Interna',
    institution_id: 'i-central',
    review_state: 'approved',
    default_line_id: 'l-gastru',
  },
  {
    id: 'd-carlos',
    full_name: 'Dr. Carlos Gómez',
    specialty: null,
    institution_id: null,
    review_state: 'approved',
    default_line_id: 'l-respi',
  },
]

function agenda(visits: VisitRow[] = []): Agenda {
  return {
    loading: false,
    tz: TZ,
    lines: LINES,
    doctors: DOCTORS,
    institutions: INSTITUTIONS,
    visits,
    byDay: new Map(),
    reports: new Map(),
    vm: (visit) => ({ visit, doctor: undefined, institution: undefined, lines: [], unsent: false, capturing: null }),
  }
}

function renderSheet(a: Agenda = agenda(), day = '2026-09-30') {
  const onClose = vi.fn()
  render(
    <ToastProvider>
      <ScheduleSheet open onClose={onClose} initialDay={day} agenda={a} />
    </ToastProvider>,
  )
  return { onClose, user: userEvent.setup() }
}

beforeEach(async () => {
  // La visita de mañana debe ofrecer las mismas horas sin depender del día ni del reloj real.
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-09-29T12:00:00Z'))
  await db.outbox.clear()
})

afterEach(() => vi.useRealTimers())

describe('Agendar una visita (doc 02 T3.2)', () => {
  it('con un médico existente son 3 toques: médico → hora → Guardar', async () => {
    const { user, onClose } = renderSheet()
    await user.click(screen.getByRole('button', { name: /Dra\. Laura Méndez/ })) // 1
    const hours = screen.getByRole('group', { name: 'Hora de la visita' })
    await user.click(within(hours).getByRole('button', { name: '9:00 AM' })) // 2 (otro día → arranca a las 8:00)
    await user.click(screen.getByRole('button', { name: 'Guardar' })) // 3

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    const [event] = await db.outbox.toArray()
    expect(event).toMatchObject({ type: 'visit_scheduled', status: 'pending' })
    expect(event!.payload).toMatchObject({
      doctor_id: 'd-laura',
      line_ids: ['l-gastru'], // la línea por defecto del médico
      scheduled_at: '2026-09-30T14:00:00.000Z', // 9:00 AM en Bogotá = 14:00 UTC
      planned_by: 'rep',
    })
    expect(event!.visit_id).toBeTruthy()
  })

  it('Guardar no se habilita hasta elegir médico y hora', async () => {
    const { user } = renderSheet()
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /Dr\. Carlos Gómez/ }))
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '8:00 AM' }))
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeEnabled()
  })

  it('busca sin distinguir tildes: «gomez» encuentra «Gómez»', async () => {
    const { user } = renderSheet()
    await user.type(screen.getByRole('searchbox', { name: 'Buscar médico' }), 'gomez')
    expect(screen.getByRole('button', { name: /Dr\. Carlos Gómez/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Laura/ })).not.toBeInTheDocument()
  })

  it('permite hasta 2 líneas y la primera es la principal', async () => {
    const { user } = renderSheet()
    await user.click(screen.getByRole('button', { name: /Dra\. Laura Méndez/ }))
    await user.click(screen.getByRole('button', { name: '8:30 AM' }))
    await user.click(
      within(screen.getByRole('group', { name: 'Línea de la visita' })).getByRole('button', { name: 'RESPI' }),
    )
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(async () => expect(await db.outbox.count()).toBe(1))
    expect((await db.outbox.toArray())[0]!.payload).toMatchObject({ line_ids: ['l-gastru', 'l-respi'] })
  })

  it('avisa (sin bloquear) si ya hay una visita a esa hora', async () => {
    const existing: VisitRow = {
      id: 'v1',
      doctor_id: 'd-carlos',
      institution_id: null,
      primary_line_id: 'l-respi',
      line_ids: ['l-respi'],
      scheduled_at: '2026-09-30T13:00:00.000Z', // 8:00 AM Bogotá
      status: 'scheduled',
      planned_by: 'rep',
      not_done_reason: null,
      updated_at: '2026-09-29T12:00:00Z',
    }
    const { user } = renderSheet(agenda([existing]))
    await user.click(screen.getByRole('button', { name: /Dra\. Laura Méndez/ }))
    await user.click(screen.getByRole('button', { name: '8:00 AM' }))
    expect(screen.getByText(/Ya tienes una visita a esa hora/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeEnabled()
  })
})

describe('Alta rápida de médico (doc 02 T3.4)', () => {
  it('crea el médico, reutiliza una institución existente y sigue con el agendado', async () => {
    const { user, onClose } = renderSheet()
    await user.click(screen.getByRole('button', { name: 'Nuevo médico' }))
    await user.type(screen.getByLabelText('Nombre del médico'), 'Dr. Pedro Ríos')
    await user.type(screen.getByLabelText('Institución (opcional)'), 'clinica central') // sin tilde ni mayúsculas
    await user.click(screen.getByRole('button', { name: 'Guardar médico' }))

    // Vuelve al agendado con el médico ya elegido.
    expect(await screen.findByText('Dr. Pedro Ríos')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '10:00 AM' }))
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())

    const events = await db.outbox.orderBy('seq').toArray()
    expect(events.map((e) => e.type)).toEqual(['doctor_created', 'visit_scheduled'])
    const doctorPayload = events[0]!.payload as Record<string, unknown>
    expect(doctorPayload).toMatchObject({ full_name: 'Dr. Pedro Ríos', institution_id: 'i-central' })
    expect(doctorPayload.institution).toBeUndefined() // no se crea una institución duplicada
    expect(events[1]!.payload).toMatchObject({ doctor_id: doctorPayload.doctor_id })
  })

  it('una institución nueva se crea en el mismo evento', async () => {
    const { user } = renderSheet()
    await user.click(screen.getByRole('button', { name: 'Nuevo médico' }))
    await user.type(screen.getByLabelText('Nombre del médico'), 'Dra. Ana Torres')
    await user.type(screen.getByLabelText('Institución (opcional)'), 'Hospital Norte')
    await user.click(screen.getByRole('button', { name: 'RESPI' }))
    await user.click(screen.getByRole('button', { name: 'Guardar médico' }))
    await waitFor(async () => expect(await db.outbox.count()).toBe(1))
    const p = (await db.outbox.toArray())[0]!.payload as Record<string, any>
    expect(p.default_line_id).toBe('l-respi')
    expect(p.institution).toMatchObject({ name: 'Hospital Norte' })
    expect(p.institution.id).toBeTruthy()
  })

  it('exige un nombre de al menos 2 letras', async () => {
    const { user } = renderSheet()
    await user.click(screen.getByRole('button', { name: 'Nuevo médico' }))
    expect(screen.getByRole('button', { name: 'Guardar médico' })).toBeDisabled()
    await user.type(screen.getByLabelText('Nombre del médico'), 'A')
    expect(screen.getByRole('button', { name: 'Guardar médico' })).toBeDisabled()
    await user.type(screen.getByLabelText('Nombre del médico'), 'na')
    expect(screen.getByRole('button', { name: 'Guardar médico' })).toBeEnabled()
  })
})
