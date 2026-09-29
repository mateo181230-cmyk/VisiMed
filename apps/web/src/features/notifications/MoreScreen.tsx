import { Bell, ChevronRight, Download, ListChecks, LogOut, MapPin, Share } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ScreenHeader } from '../../components/ScreenHeader'
import { Sheet } from '../../components/Sheet'
import { Button, Card, Notice } from '../../components/ui'
import { initials } from '../../lib/text'
import { useInstallPrompt } from '../../pwa'
import { APP_VERSION } from '../../sync/engine'
import { useOutboxCounts } from '../../sync/SyncProvider'
import { useAuth } from '../auth/AuthProvider'
import { isStandalone } from './push'

function Row({ to, icon, title, detail }: { to: string; icon: React.ReactNode; title: string; detail?: React.ReactNode }) {
  return (
    <Link to={to} className="flex min-h-16 items-center gap-3.5 px-4 py-3 active:bg-canvas">
      <span className="grid size-10 place-items-center rounded-full bg-brand-50 text-brand">{icon}</span>
      <span className="flex-1 text-[17px] font-semibold">{title}</span>
      {detail}
      <ChevronRight size={20} className="text-muted" aria-hidden />
    </Link>
  )
}

/** Más: cuenta, avisos, pendientes de envío, instalación y cierre de sesión. */
export function MoreScreen() {
  const { user, signOut } = useAuth()
  const { pending, rejected, expired } = useOutboxCounts()
  const { canInstall, install } = useInstallPrompt()
  const [confirmingLogout, setConfirmingLogout] = useState(false)
  const problems = rejected + expired
  const unsent = pending + problems
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent)

  return (
    <>
      <ScreenHeader title="Más" />
      <div className="space-y-5 px-5 pb-8">
        <Card className="flex items-center gap-4 p-5">
          <span className="grid size-14 place-items-center rounded-full bg-brand-100 text-xl font-bold text-brand">
            {initials(user?.full_name ?? '')}
          </span>
          <div className="min-w-0">
            <p className="truncate text-lg font-bold">{user?.full_name}</p>
            <p className="truncate text-muted">{user?.phone}</p>
          </div>
        </Card>

        <Card className="divide-y divide-line overflow-hidden">
          <Row to="/mas/avisos" icon={<Bell size={20} />} title="Avisos" />
          <Row to="/mas/ubicacion" icon={<MapPin size={20} />} title="Probar ubicación" />
          <Row
            to="/mas/pendientes"
            icon={<ListChecks size={20} />}
            title="Pendientes de envío"
            detail={
              unsent > 0 ? (
                <span className="rounded-full bg-warn-50 px-2.5 py-0.5 text-sm font-bold text-warn">{unsent}</span>
              ) : undefined
            }
          />
        </Card>

        {!isStandalone() && (canInstall || ios) && (
          <Card className="space-y-3 p-5">
            <h2 className="flex items-center gap-2.5 text-[17px] font-bold">
              <Download size={22} className="text-brand" /> Instalar UNO en tu teléfono
            </h2>
            {canInstall ? (
              <>
                <p className="text-[15px] text-muted">Queda como un ícono en tu pantalla y abre más rápido, también sin señal.</p>
                <Button block onClick={() => void install()}>
                  Instalar UNO
                </Button>
              </>
            ) : (
              <ol className="list-decimal space-y-1.5 pl-5 text-[15px]">
                <li>
                  Toca <Share size={16} className="inline align-text-bottom" /> <strong>Compartir</strong> en Safari.
                </li>
                <li>
                  Elige <strong>Agregar a pantalla de inicio</strong>.
                </li>
                <li>Abre UNO desde el ícono nuevo.</li>
              </ol>
            )}
          </Card>
        )}

        <Button variant="danger" block size="lg" icon={<LogOut size={20} />} onClick={() => setConfirmingLogout(true)}>
          Cerrar sesión
        </Button>
        <p className="text-center text-sm text-muted">UNO Visitas · versión {APP_VERSION}</p>
      </div>

      <Sheet open={confirmingLogout} onClose={() => setConfirmingLogout(false)} title="¿Cerrar sesión?">
        <div className="space-y-4 pt-1">
          {unsent > 0 ? (
            <Notice tone="warn">
              Tienes <strong>{unsent}</strong> {unsent === 1 ? 'cambio' : 'cambios'} que todavía no se enviaron. Si cierras
              sesión ahora se perderán.
            </Notice>
          ) : (
            <p className="text-base text-muted">Tendrás que ingresar de nuevo con tu celular y tu PIN.</p>
          )}
          <div className="flex gap-2 pb-2">
            <Button variant="outline" className="flex-1" onClick={() => setConfirmingLogout(false)}>
              {unsent > 0 ? 'Esperar' : 'Cancelar'}
            </Button>
            <Button variant="danger" className="flex-1" onClick={() => void signOut()}>
              Cerrar sesión
            </Button>
          </div>
        </div>
      </Sheet>
    </>
  )
}
