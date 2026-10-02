import { ChevronDown, type LucideIcon } from 'lucide-react'
import { useId, type ReactNode } from 'react'

/** Solo el módulo que el usuario abre monta su contenido. */
export function MobileAccordion({
  title,
  icon: Icon,
  open,
  onToggle,
  children,
}: {
  title: string
  icon?: LucideIcon
  open: boolean
  onToggle: () => void
  children: ReactNode
}) {
  const id = useId()
  return (
    <section className={`intel-disclosure${open ? ' intel-disclosure--open' : ''}`}>
      <button
        type="button"
        className="intel-disclosure-toggle"
        aria-expanded={open}
        aria-controls={id}
        onClick={onToggle}
      >
        {Icon && (
          <span className="intel-disclosure-icon">
            <Icon size={19} />
          </span>
        )}
        <span>{title}</span>
        <ChevronDown size={18} aria-hidden />
      </button>
      <div id={id} hidden={!open}>
        {open && <div className="intel-disclosure-content">{children}</div>}
      </div>
    </section>
  )
}
