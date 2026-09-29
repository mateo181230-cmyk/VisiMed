import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult, SessionOut } from '../../api/client'
import { db, getMeta, wipeLocalData } from '../../db/db'
import { AuthProvider, useAuth } from './AuthProvider'
import { LoginScreen } from './LoginScreen'

const login = vi.fn<(phone: string, pin: string) => Promise<ApiResult<SessionOut>>>()

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    login: (phone: string, pin: string) => login(phone, pin),
    logout: vi.fn(async () => {}),
    configureAuthHandlers: vi.fn(),
    setAccessToken: vi.fn(),
  }
})

const session = (id = 'u1'): SessionOut => ({
  access_token: 'tok',
  token_type: 'bearer',
  expires_at: '2026-09-30T00:00:00Z',
  user: { id, full_name: 'Ana Rep', role: 'rep', phone: '+573001112233', timezone: 'America/Bogota' },
})

function renderLogin() {
  render(
    <MemoryRouter initialEntries={['/login']}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginScreen />} />
          <Route path="/" element={<p>Pantalla Hoy</p>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
  return userEvent.setup()
}

beforeEach(async () => {
  login.mockReset()
  await wipeLocalData()
})

describe('Ingreso', () => {
  it('normaliza el celular colombiano a E.164 y entra a Hoy', async () => {
    login.mockResolvedValue({ ok: true, data: session() })
    const user = renderLogin()
    await user.type(await screen.findByLabelText('Celular'), '300 111 2233')
    await user.type(screen.getByLabelText('PIN de 6 dígitos'), '246810')
    await user.click(screen.getByRole('button', { name: 'Entrar' }))
    expect(await screen.findByText('Pantalla Hoy')).toBeInTheDocument()
    expect(login).toHaveBeenCalledWith('+573001112233', '246810')
    expect((await getMeta<{ full_name: string }>('user'))?.full_name).toBe('Ana Rep')
  })

  it('el botón exige celular y PIN completo; el PIN solo admite dígitos', async () => {
    const user = renderLogin()
    const enter = await screen.findByRole('button', { name: 'Entrar' })
    expect(enter).toBeDisabled()
    await user.type(screen.getByLabelText('Celular'), '3001112233')
    await user.type(screen.getByLabelText('PIN de 6 dígitos'), '12ab34')
    expect(screen.getByLabelText('PIN de 6 dígitos')).toHaveValue('1234')
    expect(enter).toBeDisabled()
  })

  it.each([
    [{ ok: false, kind: 'auth', status: 401 }, 'Celular o PIN incorrectos.'],
    [{ ok: false, kind: 'server', status: 429 }, 'Demasiados intentos'],
    [{ ok: false, kind: 'network' }, 'Necesitas conexión para ingresar'],
  ] as const)('muestra el error en español (%#)', async (failure, message) => {
    login.mockResolvedValue(failure as ApiResult<SessionOut>)
    const user = renderLogin()
    await user.type(await screen.findByLabelText('Celular'), '3001112233')
    await user.type(screen.getByLabelText('PIN de 6 dígitos'), '000000')
    await user.click(screen.getByRole('button', { name: 'Entrar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(screen.getByLabelText('PIN de 6 dígitos')).toHaveValue('') // se limpia el PIN
  })

})

describe('Cambio de usuario en el mismo teléfono', () => {
  const pendingEvent = {
    event_id: 'e1',
    type: 'visit_scheduled',
    visit_id: 'v1',
    device_ts: '2026-09-29T12:00:00Z',
    payload: {},
    status: 'pending' as const,
    attempts: 0,
    created_at: '2026-09-29T12:00:00Z',
  }

  function Probe() {
    const auth = useAuth()
    return <button onClick={() => void auth.signIn('3001112233', '246810')}>ingresar</button>
  }

  async function signInAs(id: string) {
    login.mockResolvedValue({ ok: true, data: session(id) })
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'ingresar' }))
    await waitFor(async () => expect((await getMeta<{ id: string }>('user'))?.id).toBe(id))
  }

  it('si entra otro visitador se borran los datos y la cola del anterior', async () => {
    await db.meta.put({ key: 'user', value: session('anterior').user })
    await db.outbox.add(pendingEvent)
    await signInAs('nuevo')
    expect(await db.outbox.count()).toBe(0) // nunca se enviarían los cambios de otro usuario
  })

  it('si vuelve el mismo visitador se conserva su cola (no se pierde nada al reingresar)', async () => {
    await db.meta.put({ key: 'user', value: session('u1').user })
    await db.outbox.add(pendingEvent)
    await signInAs('u1')
    expect(await db.outbox.count()).toBe(1)
  })
})
