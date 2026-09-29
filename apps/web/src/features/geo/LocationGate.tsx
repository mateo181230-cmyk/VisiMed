import { MapPin } from 'lucide-react'
import { type ReactNode, useCallback, useEffect, useState } from 'react'
import { Button, Notice } from '../../components/ui'
import { capturarUbicacion, contextoSeguro, estadoPermiso, observarPermiso, ubicacionDisponible } from './capturar'
import type { PermisoUbicacion } from './tipos'

/** Estado del permiso de ubicación, siempre al día (también al volver de los ajustes del teléfono). */
export function usePermisoUbicacion() {
  const [estado, setEstado] = useState<PermisoUbicacion | 'loading'>('loading')
  const [pidiendo, setPidiendo] = useState(false)

  const comprobar = useCallback(async () => setEstado(await estadoPermiso()), [])

  useEffect(() => {
    void comprobar()
    const dejar = observarPermiso(setEstado)
    const alVolver = (): void => {
      if (document.visibilityState === 'visible') void comprobar()
    }
    document.addEventListener('visibilitychange', alVolver)
    return () => {
      dejar()
      document.removeEventListener('visibilitychange', alVolver)
    }
  }, [comprobar])

  /** Dispara el aviso del sistema (solo se puede hacer pidiendo una lectura) y vuelve a comprobar. */
  const pedir = useCallback(async () => {
    setPidiendo(true)
    try {
      await capturarUbicacion()
      await comprobar()
    } finally {
      setPidiendo(false)
    }
  }, [comprobar])

  return { estado, pidiendo, pedir, comprobar }
}

function Instrucciones() {
  const ua = typeof navigator === 'undefined' ? '' : navigator.userAgent
  if (/iPad|iPhone|iPod/.test(ua)) {
    return (
      <ol className="list-decimal space-y-1.5 pl-5 text-[15px]">
        <li>
          Abre <strong>Ajustes</strong> del iPhone › <strong>Privacidad y seguridad</strong> ›{' '}
          <strong>Localización</strong>.
        </li>
        <li>
          Elige <strong>Safari</strong> (o <strong>UNO</strong> si la instalaste) y marca{' '}
          <strong>Al usar la app</strong>.
        </li>
        <li>Vuelve a UNO.</li>
      </ol>
    )
  }
  if (/Android/.test(ua)) {
    return (
      <ol className="list-decimal space-y-1.5 pl-5 text-[15px]">
        <li>
          Toca el candado junto a la dirección › <strong>Permisos</strong> › <strong>Ubicación</strong> ›{' '}
          <strong>Permitir</strong>.
        </li>
        <li>
          Si instalaste UNO: mantén pulsado su ícono › <strong>Información de la app</strong> ›{' '}
          <strong>Permisos</strong>.
        </li>
        <li>Vuelve a UNO.</li>
      </ol>
    )
  }
  return (
    <p className="text-[15px]">
      Haz clic en el candado junto a la dirección, permite la <strong>ubicación</strong> para este sitio y vuelve a UNO.
    </p>
  )
}

/** Pantalla que bloquea la app hasta que el visitador concede la ubicación. */
function PantallaPermiso({
  estado,
  pidiendo,
  pedir,
  comprobar,
  footer,
}: {
  estado: PermisoUbicacion
  pidiendo: boolean
  pedir: () => Promise<void>
  comprobar: () => Promise<void>
  footer?: ReactNode
}) {
  const seguro = contextoSeguro()
  const sinApi = !ubicacionDisponible()
  return (
    <div className="flex min-h-dvh flex-col justify-center gap-6 px-6 py-10">
      <span className="grid size-16 place-items-center rounded-full bg-brand-100 text-brand">
        <MapPin size={32} aria-hidden />
      </span>
      <div className="space-y-3">
        <h1 className="text-[30px] leading-tight font-extrabold tracking-tight">Activa tu ubicación</h1>
        <p className="text-[17px]">
          UNO necesita tu ubicación para confirmar dónde estás cuando tocas <strong>Llegué</strong> y{' '}
          <strong>Terminé</strong>.
        </p>
        <p className="text-[15px] text-muted">
          Solo la usamos en esos dos toques. No te seguimos ni guardamos tu recorrido.
        </p>
      </div>

      {!seguro && (
        <Notice tone="danger">
          Esta página no está en HTTPS, así que el navegador no entrega la ubicación. Abre UNO desde su dirección
          segura.
        </Notice>
      )}
      {seguro && sinApi && (
        <Notice tone="danger">Este navegador no ofrece ubicación. Abre UNO en Chrome o Safari.</Notice>
      )}

      {seguro && !sinApi && estado === 'denied' && (
        <div className="space-y-3">
          <Notice tone="warn">El permiso de ubicación está bloqueado. Actívalo en los ajustes para continuar.</Notice>
          <Instrucciones />
          <Button size="lg" block onClick={() => void comprobar()}>
            Ya lo activé
          </Button>
        </div>
      )}

      {seguro && !sinApi && estado !== 'denied' && (
        <Button size="lg" block icon={<MapPin size={22} />} disabled={pidiendo} onClick={() => void pedir()}>
          {pidiendo ? 'Esperando tu permiso…' : 'Permitir ubicación'}
        </Button>
      )}
      {footer}
    </div>
  )
}

/**
 * El permiso de ubicación es obligatorio (decisión del cliente, 28 sep 2026): sin él no se entra a la app.
 * Una lectura que falla NO bloquea (el toque se registra sin ubicación); lo que bloquea es no tener permiso.
 * `footer` es lo que se muestra al pie de la pantalla de bloqueo (por ejemplo, salir de la cuenta).
 */
export function RequireLocation({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  const { estado, pidiendo, pedir, comprobar } = usePermisoUbicacion()
  if (estado === 'loading') return <div className="min-h-dvh" aria-busy />
  if (estado === 'granted') return <>{children}</>
  return <PantallaPermiso estado={estado} pidiendo={pidiendo} pedir={pedir} comprobar={comprobar} footer={footer} />
}
