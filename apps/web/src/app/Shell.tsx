import { RefreshCw } from 'lucide-react'
import { Outlet, Link } from 'react-router-dom'
import { BottomNav } from '../components/BottomNav'
import { Button } from '../components/ui'
import { usePwaUpdate } from '../pwa'
import { useOutboxCounts } from '../sync/SyncProvider'
import { useAuth } from '../features/auth/AuthProvider'
import { RequireLocation } from '../features/geo/LocationGate'

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
 * Marco de las pantallas del visitador: contenido + barra inferior; Inteligencia tiene su propio marco.
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
