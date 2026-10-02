import clsx from 'clsx'
import { CalendarDays, GraduationCap, House, Sparkles } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'

/** Los mismos cuatro destinos en toda la experiencia del visitador. */
export function BottomNav({
  recommendationsPath = '/inteligencia',
  agendaPath = '/agenda',
  section,
}: {
  recommendationsPath?: string
  agendaPath?: string
  section?: 'recommendations' | 'agenda'
}) {
  const { pathname } = useLocation()
  const items = [
    { to: '/', label: 'Hoy', icon: House, active: pathname === '/' },
    { to: agendaPath, label: 'Agenda', icon: CalendarDays, active: section === 'agenda' || pathname === '/agenda' },
    {
      to: recommendationsPath,
      label: 'Recomendaciones',
      icon: Sparkles,
      active: section === 'recommendations' || (!section && pathname.startsWith('/inteligencia')),
    },
    { to: '/entrenar', label: 'Entrenar', icon: GraduationCap, active: pathname.startsWith('/entrenar') },
  ]
  return (
    <nav
      aria-label="Principal"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-white/95 backdrop-blur"
    >
      <ul className="mx-auto grid w-full max-w-[480px] grid-cols-4 pb-[var(--safe-bottom)] max-[360px]:grid-cols-[1fr_1fr_1.5fr_1fr]">
        {items.map(({ to, label, icon: Icon, active }) => (
          <li key={to}>
            <Link
              to={to}
              aria-current={active ? 'page' : undefined}
              className={clsx(
                'flex min-h-[68px] flex-col items-center justify-center gap-1 px-1 text-[11px] font-semibold',
                active ? 'text-brand' : 'text-muted',
              )}
            >
              <Icon size={24} strokeWidth={active ? 2.5 : 1.8} aria-hidden />
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}
