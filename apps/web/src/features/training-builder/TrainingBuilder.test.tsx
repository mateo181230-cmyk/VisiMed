import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TrainingBuilder } from './TrainingBuilder'
import { STORAGE_KEY, readPrograms } from './model'

vi.mock('../auth/AuthProvider', () => ({
  useAuth: () => ({ user: { role: 'rep', full_name: 'Visitador' } }),
}))

function mount() {
  return render(<MemoryRouter initialEntries={['/admin/training/demo']}><Routes><Route path="/admin/training/demo/:levelId?" element={<TrainingBuilder demo />} /></Routes></MemoryRouter>)
}

beforeEach(() => localStorage.clear())

describe('Training Builder de presentación', () => {
  it('crea un nivel, guarda su evaluación y la recupera al volver a abrir la demo', async () => {
    const user = userEvent.setup()
    const app = mount()
    await user.click(screen.getByRole('button', { name: 'Crear nivel' }))
    await user.clear(screen.getByLabelText('Nombre del nivel'))
    await user.type(screen.getByLabelText('Nombre del nivel'), 'Objeción de precio')
    await user.click(screen.getByRole('button', { name: 'Evaluación' }))
    await user.clear(screen.getByRole('spinbutton', { name: 'Puntaje mínimo para aprobar' }))
    await user.type(screen.getByRole('spinbutton', { name: 'Puntaje mínimo para aprobar' }), '85')
    await user.click(screen.getByRole('button', { name: 'Guardar nivel' }))
    expect(readPrograms()[0]?.levels.at(-1)?.passingScore).toBe(85)
    expect(readPrograms()[0]?.levels).toHaveLength(5)
    app.unmount()
    mount()
    expect(screen.getByRole('button', { name: 'Objeción de precio' })).toBeInTheDocument()
    expect(screen.getByText('85/100 para aprobar')).toBeInTheDocument()
  })

  it('bloquea guardar pesos incompletos y permite recorrer la simulación sin llamar al proveedor', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(screen.getByRole('button', { name: 'Explorar antes de presentar' }))
    await user.click(screen.getByRole('button', { name: 'Evaluación' }))
    const weight = screen.getByRole('spinbutton', { name: 'Peso de Descubrimiento' })
    await user.clear(weight)
    await user.type(weight, '10')
    await user.click(screen.getByRole('button', { name: 'Guardar nivel' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Los pesos de los objetivos activos deben sumar 100 %')
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    await user.clear(weight)
    await user.type(weight, '20')
    await user.click(screen.getAllByRole('button', { name: 'Probar escenario' })[0]!)
    const dialog = screen.getByRole('dialog', { name: 'Explorar antes de presentar' })
    expect(dialog).toHaveTextContent('No usa el micrófono, no conecta con Tavus')
    await user.click(within(dialog).getByRole('button', { name: 'Comenzar ejemplo' }))
    await user.click(within(dialog).getByRole('button', { name: 'Avanzar conversación de ejemplo' }))
    await user.click(within(dialog).getByRole('button', { name: 'Finalizar' }))
    expect(screen.getByRole('dialog', { name: 'Resultado de ejemplo' })).toHaveTextContent('83/100')
    expect(screen.getByText('Qué mejorar')).toBeInTheDocument()
  })

  it('duplica como borrador sin modificar el nivel original y ofrece eliminación explícita', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(screen.getByRole('button', { name: 'Duplicar Explorar antes de presentar' }))
    const levels = readPrograms()[0]!.levels
    expect(levels).toHaveLength(5)
    expect(levels[0]!.status).toBe('active')
    expect(levels[1]!.status).toBe('draft')
    expect(levels[1]!.objectives[0]!.id).not.toBe(levels[0]!.objectives[0]!.id)
    const options = screen.getByLabelText('Más opciones de Explorar antes de presentar · Copia')
    await user.click(options)
    const card = options.closest('article')!
    await user.click(within(card).getByRole('button', { name: 'Eliminar nivel' }))
    expect(screen.getByRole('dialog', { name: 'Eliminar nivel de la demostración' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Eliminar de la demo' }))
    expect(readPrograms()[0]!.levels).toHaveLength(4)
  })

  it('no abre la ruta administrativa a un visitador', () => {
    render(<MemoryRouter><TrainingBuilder /></MemoryRouter>)
    expect(screen.getByRole('heading', { name: 'Acceso de administrador' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Crear nivel' })).not.toBeInTheDocument()
  })
})
