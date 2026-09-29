import clsx from 'clsx'
import { CalendarDays, Ellipsis, GraduationCap, History, House, RefreshCw } from 'lucide-react'
import { NavLink, Outlet, useLocation, Link } from 'react-router-dom'
import { Button } from '../components/ui'
import { usePwaUpdate } from '../pwa'
import { useOutboxCounts } from '../sync/SyncProvider'
import { useAuth } from '../features/auth/AuthProvider'
import { RequireLocation } from '../features/geo/LocationGate'
import { useToConfirmCount } from '../features/history/useHistory'

const ITEMS = [
  { to: '/', label: 'Hoy', icon: House, end: true },
  { to: '/agenda', label: 'Agenda', icon: CalendarDays, end: false },
  { to: '/historial', label: 'Historial', icon: History, end: false },
  { to: '/entrenar', label: 'Entrenar', icon: GraduationCap, end: false },
  { to: '/mas', label: 'Más', icon: Ellipsis, end: false },
] as const

function BottomNav() {
  const { pathname } = useLocation()
  const toConfirm = useToConfirmCount()
  return (
    <nav
      aria-label="Principal"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-white/95 backdrop-blur"
    >
      <ul className="mx-auto grid max-w-[480px] grid-cols-5 pb-[var(--safe-bottom)]">
        {ITEMS.map(({ to, label, icon: Icon, end }) => {
          const active = end ? pathname === to : pathname.startsWith(to)
          return (
            <li key={to}>
              <NavLink
                to={to}
                end={end}
                aria-current={active ? 'page' : undefined}
                className={clsx(
                  'flex min-h-[68px] flex-col items-center justify-center gap-1 text-[13px] font-semibold',
                  active ? 'text-brand' : 'text-muted',
                )}
              >
                <span className="relative">
                  <Icon size={26} strokeWidth={active ? 2.5 : 2} aria-hidden />
                  {to === '/historial' && toConfirm > 0 && (
                    <span
                      aria-label={`${toConfirm} por confirmar`}
                      className="absolute -top-1.5 -right-2.5 grid min-w-[18px] place-items-center rounded-full bg-danger px-1 text-[11px] leading-[18px] font-bold text-white"
                    >
                      {toConfirm}
                    </span>
                  )}
                </span>
                {label}
              </NavLink>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

function Banners() {
  const { needsReauth } = useAuth()
  const { needRefresh, update } = usePwaUpdate()
  if (!needsReauth && !needRefresh) return null
  return (
    <div className="space-y-2 px-4 pt-[calc(8px+var(--safe-top))]">
      {needsReauth && (
        <div
          role="status"
          className="flex items-center justify-between gap-3 rounded-control bg-warn-50 px-3.5 py-2.5 text-[15px] text-warn"
        >
          <span>Tu sesión venció. Tus cambios se conservan.</span>
          <Link to="/login" className="min-h-10 shrink-0 rounded-control px-2 py-2 font-bold underline">
            Ingresar
          </Link>
        </div>
      )}
      {needRefresh && (
        <div
          role="status"
          className="flex items-center justify-between gap-3 rounded-control bg-brand-50 px-3.5 py-2.5 text-[15px] text-navy"
        >
          <span>Hay una versión nueva de UNO.</span>
          <Button variant="soft" className="min-h-10 shrink-0 px-3" icon={<RefreshCw size={16} />} onClick={update}>
            Actualizar
          </Button>
        </div>
      )}
    </div>
  )
}

/** Salida de la pantalla de bloqueo por falta de ubicación. No se ofrece si cerrar sesión perdería cambios sin enviar. */
function LogoutWhenBlocked() {
  const { signOut } = useAuth()
  const { pending, rejected, expired } = useOutboxCounts()
  if (pending + rejected + expired > 0) return null
  return (
    <Button variant="ghost" block onClick={() => void signOut()}>
      Cerrar sesión
    </Button>
  )
}

/**
 * Marco de las pantallas del visitador: contenido + barra inferior (Hoy · Agenda · Historial · Entrenar · Más).
 * Sin permiso de ubicación solo se ve la pantalla que lo pide (`RequireLocation`).
 */
export function Shell() {
  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-[480px] flex-col">
      <Banners />
      <RequireLocation footer={<LogoutWhenBlocked />}>
        <main className="flex-1 pb-[calc(92px+var(--safe-bottom))]">
          <Outlet />
        </main>
        <BottomNav />
      </RequireLocation>
    </div>
  )
}
