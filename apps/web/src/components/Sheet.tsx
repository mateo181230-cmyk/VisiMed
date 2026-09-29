import { X } from 'lucide-react'
import { type ReactNode, useEffect, useId, useRef } from 'react'

interface SheetProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
}

/** Hoja inferior (doc 01 §8.3, S7). Se cierra con Escape, tocando fuera o con la «X». */
export function Sheet({ open, onClose, title, children, footer }: SheetProps) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  const previouslyFocused = useRef<Element | null>(null)

  useEffect(() => {
    if (!open) return
    previouslyFocused.current = document.activeElement
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const { overflow } = document.body.style
    document.body.style.overflow = 'hidden'
    panel.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      if (previouslyFocused.current instanceof HTMLElement) previouslyFocused.current.focus()
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      <div
        className="absolute inset-0 animate-[fade-in_.15s_ease-out] bg-ink/45"
        onClick={onClose}
        aria-hidden
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative flex max-h-[92dvh] w-full max-w-[480px] animate-[sheet-up_.2s_ease-out] flex-col rounded-t-3xl bg-white shadow-xl outline-none"
      >
        <header className="flex items-center justify-between gap-2 px-5 pt-4 pb-2">
          <h2 id={titleId} className="text-xl font-bold">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="-mr-2 grid size-12 place-items-center rounded-full text-muted active:bg-canvas"
          >
            <X size={24} />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-5 pb-3">{children}</div>
        {footer ? (
          <footer className="border-t border-line bg-white px-5 pt-3 pb-[calc(12px+var(--safe-bottom))]">
            {footer}
          </footer>
        ) : (
          <div className="pb-[var(--safe-bottom)]" />
        )}
      </div>
    </div>
  )
}
