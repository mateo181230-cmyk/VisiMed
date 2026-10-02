import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { Sheet } from './Sheet'

it('conserva el foco de escritura al refrescar el contenido y usa el cierre actual', async () => {
  const user = userEvent.setup()
  const firstClose = vi.fn()
  const latestClose = vi.fn()
  const view = render(<Sheet open title="Resumen" onClose={firstClose}><textarea aria-label="Resumen" /></Sheet>)
  const input = screen.getByRole('textbox', { name: 'Resumen' })
  await user.type(input, 'Presenté el producto.')
  view.rerender(<Sheet open title="Resumen" onClose={latestClose}><textarea aria-label="Resumen" /></Sheet>)
  expect(input).toHaveFocus()
  await user.keyboard(' El médico pidió información.')
  expect(input).toHaveValue('Presenté el producto. El médico pidió información.')
  await user.keyboard('{Escape}')
  expect(latestClose).toHaveBeenCalledOnce()
  expect(firstClose).not.toHaveBeenCalled()
})
