import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import { RegisterScreen } from './RegisterScreen'

const signUp = vi.hoisted(() => vi.fn().mockResolvedValue(null))
vi.mock('./AuthProvider', () => ({ useAuth: () => ({ status: 'anon', signUp }) }))

it('registra al visitador con celular, correo e invitación y abre la app', async () => {
  const user = userEvent.setup()
  render(
    <MemoryRouter initialEntries={['/registro']}>
      <Routes>
        <Route path="/registro" element={<RegisterScreen />} />
        <Route path="/" element={<p>Inicio</p>} />
      </Routes>
    </MemoryRouter>,
  )
  await user.type(screen.getByLabelText('Nombre'), 'Mateo Prueba')
  await user.type(screen.getByLabelText('Celular'), '3004198710')
  await user.type(screen.getByLabelText('Correo'), 'mateo@example.com')
  await user.type(screen.getByLabelText('PIN de 6 dígitos'), '123456')
  await user.type(screen.getByLabelText('Código de invitación'), 'codigo-piloto')
  await user.click(screen.getByRole('button', { name: 'Crear cuenta' }))
  expect(signUp).toHaveBeenCalledWith('Mateo Prueba', '3004198710', 'mateo@example.com', '123456', 'codigo-piloto')
  expect(await screen.findByText('Inicio')).toBeInTheDocument()
})
