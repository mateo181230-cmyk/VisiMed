import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PermisoUbicacion } from './tipos'

const mocks = vi.hoisted(() => ({
  estadoPermiso: vi.fn<() => Promise<PermisoUbicacion>>(),
  capturarUbicacion: vi.fn(),
  contextoSeguro: vi.fn(() => true),
  ubicacionDisponible: vi.fn(() => true),
  alCambiar: null as null | ((e: PermisoUbicacion) => void),
}))

vi.mock('./capturar', () => ({
  estadoPermiso: mocks.estadoPermiso,
  capturarUbicacion: mocks.capturarUbicacion,
  contextoSeguro: mocks.contextoSeguro,
  ubicacionDisponible: mocks.ubicacionDisponible,
  observarPermiso: (fn: (e: PermisoUbicacion) => void) => {
    mocks.alCambiar = fn
    return () => {
      mocks.alCambiar = null
    }
  },
}))

import { RequireLocation } from './LocationGate'

const app = () =>
  render(
    <RequireLocation>
      <p>Contenido de la app</p>
    </RequireLocation>,
  )

beforeEach(() => {
  mocks.estadoPermiso.mockReset()
  mocks.capturarUbicacion.mockReset().mockResolvedValue({})
  mocks.contextoSeguro.mockReturnValue(true)
  mocks.ubicacionDisponible.mockReturnValue(true)
  mocks.alCambiar = null
})

describe('permiso de ubicación obligatorio', () => {
  it('con permiso concedido se ve la app', async () => {
    mocks.estadoPermiso.mockResolvedValue('granted')
    app()
    expect(await screen.findByText('Contenido de la app')).toBeInTheDocument()
    expect(screen.queryByText('Activa tu ubicación')).not.toBeInTheDocument()
  })

  it('sin permiso NO se ve la app: solo la pantalla que lo pide y por qué', async () => {
    mocks.estadoPermiso.mockResolvedValue('prompt')
    app()
    expect(await screen.findByRole('heading', { name: 'Activa tu ubicación' })).toBeInTheDocument()
    expect(screen.getByText(/No te seguimos ni guardamos tu recorrido/)).toBeInTheDocument()
    expect(screen.queryByText('Contenido de la app')).not.toBeInTheDocument()
  })

  it('«Permitir ubicación» dispara el aviso del sistema y, si lo aceptan, abre la app', async () => {
    mocks.estadoPermiso.mockResolvedValueOnce('prompt').mockResolvedValue('granted')
    const user = userEvent.setup()
    app()
    await user.click(await screen.findByRole('button', { name: 'Permitir ubicación' }))
    expect(mocks.capturarUbicacion).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('Contenido de la app')).toBeInTheDocument()
  })

  it('si lo rechazan, sigue bloqueada y explica cómo activarlo en los ajustes', async () => {
    mocks.estadoPermiso.mockResolvedValueOnce('prompt').mockResolvedValue('denied')
    const user = userEvent.setup()
    app()
    await user.click(await screen.findByRole('button', { name: 'Permitir ubicación' }))
    expect(await screen.findByText(/permiso de ubicación está bloqueado/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ya lo activé' })).toBeInTheDocument()
    expect(screen.queryByText('Contenido de la app')).not.toBeInTheDocument()
  })

  it('«Ya lo activé» vuelve a comprobar y deja pasar', async () => {
    mocks.estadoPermiso.mockResolvedValueOnce('denied').mockResolvedValue('granted')
    const user = userEvent.setup()
    app()
    await user.click(await screen.findByRole('button', { name: 'Ya lo activé' }))
    expect(await screen.findByText('Contenido de la app')).toBeInTheDocument()
  })

  it('si el usuario lo activa en los ajustes, la app se abre sola', async () => {
    mocks.estadoPermiso.mockResolvedValue('denied')
    app()
    await screen.findByRole('button', { name: 'Ya lo activé' })
    await waitFor(() => expect(mocks.alCambiar).not.toBeNull())
    act(() => mocks.alCambiar!('granted'))
    expect(await screen.findByText('Contenido de la app')).toBeInTheDocument()
  })

  it('y si lo revoca con la app abierta, vuelve a bloquearse', async () => {
    mocks.estadoPermiso.mockResolvedValue('granted')
    app()
    await screen.findByText('Contenido de la app')
    await waitFor(() => expect(mocks.alCambiar).not.toBeNull())
    act(() => mocks.alCambiar!('denied'))
    expect(await screen.findByRole('heading', { name: 'Activa tu ubicación' })).toBeInTheDocument()
    expect(screen.queryByText('Contenido de la app')).not.toBeInTheDocument()
  })

  it('la pantalla de bloqueo muestra el pie que le pasen (por ejemplo, cerrar sesión) y la app abierta no', async () => {
    mocks.estadoPermiso.mockResolvedValueOnce('denied').mockResolvedValue('granted')
    const user = userEvent.setup()
    render(
      <RequireLocation footer={<button type="button">Salir</button>}>
        <p>Contenido de la app</p>
      </RequireLocation>,
    )
    expect(await screen.findByRole('button', { name: 'Salir' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Ya lo activé' }))
    expect(await screen.findByText('Contenido de la app')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Salir' })).not.toBeInTheDocument()
  })

  it('fuera de HTTPS lo dice y no ofrece un botón que no puede funcionar', async () => {
    mocks.estadoPermiso.mockResolvedValue('prompt')
    mocks.contextoSeguro.mockReturnValue(false)
    app()
    expect(await screen.findByText(/no está en HTTPS/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Permitir ubicación' })).not.toBeInTheDocument()
  })

  it('en un navegador sin ubicación lo dice claro', async () => {
    mocks.estadoPermiso.mockResolvedValue('prompt')
    mocks.ubicacionDisponible.mockReturnValue(false)
    app()
    expect(await screen.findByText(/no ofrece ubicación/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Permitir ubicación' })).not.toBeInTheDocument()
  })
})
