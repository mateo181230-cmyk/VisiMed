import clsx from 'clsx'
import { BellRing, ChevronLeft, Mail, Send, Smartphone } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { type ApiFailure, type Preferences, notifications } from '../../api/client'
import { ScreenHeader } from '../../components/ScreenHeader'
import { useToast } from '../../components/Toast'
import { Button, Card, Chip, Field, Notice, Skeleton } from '../../components/ui'
import { useOnline } from '../../sync/SyncProvider'
import { currentSubscription, disablePush, enablePush, pushSupport } from './push'

const failureMessage = (f: ApiFailure): string => {
  if (f.kind === 'network') return 'Sin conexión. Los ajustes de avisos necesitan internet.'
  if (f.kind === 'auth') return 'Tu sesión venció. Ingresa de nuevo.'
  return f.message ?? 'No pudimos completar la acción. Inténtalo de nuevo.'
}

function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={clsx(
        'relative h-8 w-14 shrink-0 rounded-full transition-colors disabled:opacity-50',
        checked ? 'bg-brand' : 'bg-line',
      )}
    >
      <span
        className={clsx(
          'absolute top-1 size-6 rounded-full bg-white shadow transition-all',
          checked ? 'left-7' : 'left-1',
        )}
      />
    </button>
  )
}

function CardHeader({ icon, title, right }: { icon: React.ReactNode; title: string; right?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h2 className="flex items-center gap-2.5 text-[17px] font-bold">
        <span className="text-brand">{icon}</span>
        {title}
      </h2>
      {right}
    </div>
  )
}

/** Avisos: notificaciones en el teléfono (Web Push) y por correo. */
export function NotificationsScreen() {
  const online = useOnline()
  const toast = useToast()
  const [prefs, setPrefs] = useState<Preferences | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const res = await notifications.get()
    if (res.ok) {
      setPrefs(res.data)
      setLoadError(null)
    } else {
      setLoadError(failureMessage(res))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, online])

  return (
    <>
      <div className="px-2 pt-[calc(8px+var(--safe-top))]">
        <Link
          to="/mas"
          className="inline-flex min-h-12 items-center gap-1 rounded-control px-2 font-semibold text-brand active:bg-brand-50"
        >
          <ChevronLeft size={22} /> Más
        </Link>
      </div>
      <ScreenHeader title="Avisos" subtitle="Cómo y cuándo quieres que te avisemos" />

      <div className="space-y-4 px-5 pb-8">
        {!online && <Notice tone="warn">Sin conexión: puedes ver tus ajustes, pero cambiarlos necesita internet.</Notice>}
        {loadError && !prefs && <Notice tone="warn">{loadError}</Notice>}
        {!prefs && !loadError && <Skeleton className="h-48" />}
        {prefs && (
          <>
            <PushCard prefs={prefs} onChange={setPrefs} />
            <EmailCard prefs={prefs} onChange={setPrefs} onReload={load} />
            <WhenCard prefs={prefs} onChange={setPrefs} />
            <TestCard prefs={prefs} onDone={(m) => toast.show(m)} />
          </>
        )}
      </div>
    </>
  )
}

// --------------------------------------------------------------------------- teléfono

function PushCard({ prefs, onChange }: { prefs: Preferences; onChange: (p: Preferences) => void }) {
  const [support, setSupport] = useState(pushSupport())
  const [here, setHere] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void currentSubscription().then((s) => setHere(s !== null))
  }, [prefs.push_subscriptions])

  async function turnOn(): Promise<void> {
    if (!prefs.vapid_public_key) return
    setBusy(true)
    setError(null)
    try {
      const device = await enablePush(prefs.vapid_public_key)
      const res = await notifications.subscribe(device.endpoint, device.p256dh, device.auth)
      if (res.ok) {
        onChange(res.data)
        setHere(true)
      } else {
        setError(failureMessage(res))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No pudimos activar los avisos.')
    } finally {
      setSupport(pushSupport())
      setBusy(false)
    }
  }

  async function turnOff(): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      const endpoint = await disablePush()
      if (endpoint) {
        const res = await notifications.unsubscribe(endpoint)
        if (res.ok) onChange(res.data)
        else setError(failureMessage(res))
      }
      setHere(false)
    } catch {
      setError('No pudimos desactivar los avisos en este teléfono.')
    } finally {
      setBusy(false)
    }
  }

  const active = here === true && prefs.push_enabled
  return (
    <Card className="space-y-3 p-5">
      <CardHeader
        icon={<Smartphone size={22} />}
        title="Avisos en este teléfono"
        right={
          <span className={clsx('text-sm font-semibold', active ? 'text-ok' : 'text-muted')}>
            {active ? 'Activados' : 'Desactivados'}
          </span>
        }
      />
      {!prefs.push_available ? (
        <Notice tone="warn">
          El servidor todavía no tiene configuradas las llaves de notificaciones (VAPID). Pídele al administrador que las
          agregue.
        </Notice>
      ) : support === 'needs-install' ? (
        <Notice tone="info">
          En iPhone los avisos solo funcionan con la app instalada. Toca <strong>Compartir</strong> y luego{' '}
          <strong>Agregar a pantalla de inicio</strong>; abre UNO desde ahí y vuelve aquí.
        </Notice>
      ) : support === 'unsupported' ? (
        <Notice tone="warn">Este navegador no puede recibir avisos. Prueba con Chrome, o instala la app.</Notice>
      ) : support === 'denied' ? (
        <Notice tone="warn">
          Bloqueaste los avisos para este sitio. Actívalos desde los ajustes del navegador (candado junto a la dirección)
          y vuelve.
        </Notice>
      ) : (
        <>
          <p className="text-[15px] text-muted">
            Te recordamos tus visitas y te enviamos el resumen del día, aunque la app esté cerrada.
          </p>
          {active ? (
            <Button variant="outline" block disabled={busy} onClick={() => void turnOff()}>
              Desactivar en este teléfono
            </Button>
          ) : (
            <Button block size="lg" icon={<BellRing size={20} />} disabled={busy} onClick={() => void turnOn()}>
              {busy ? 'Activando…' : 'Activar avisos'}
            </Button>
          )}
        </>
      )}
      {prefs.push_subscriptions > 1 && (
        <p className="text-sm text-muted">Tienes {prefs.push_subscriptions} dispositivos con avisos activos.</p>
      )}
      {error && <Notice tone="danger">{error}</Notice>}
    </Card>
  )
}

// --------------------------------------------------------------------------- correo

function EmailCard({
  prefs,
  onChange,
  onReload,
}: {
  prefs: Preferences
  onChange: (p: Preferences) => void
  onReload: () => Promise<void>
}) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [awaitingCode, setAwaitingCode] = useState<string | null>(prefs.pending_email ?? null)
  const [changing, setChanging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function sendCode(): Promise<void> {
    setBusy(true)
    setError(null)
    const res = await notifications.registerEmail(email.trim())
    setBusy(false)
    if (res.ok) {
      setAwaitingCode(res.data.email)
      setCode('')
    } else {
      setError(failureMessage(res))
    }
  }

  async function verify(): Promise<void> {
    setBusy(true)
    setError(null)
    const res = await notifications.verifyEmail(code)
    setBusy(false)
    if (res.ok) {
      onChange(res.data)
      setAwaitingCode(null)
      setChanging(false)
      setEmail('')
    } else {
      setError(failureMessage(res))
    }
  }

  async function toggle(enabled: boolean): Promise<void> {
    const res = await notifications.update({ email_enabled: enabled })
    if (res.ok) onChange(res.data)
    else setError(failureMessage(res))
  }

  async function remove(): Promise<void> {
    const res = await notifications.removeEmail()
    if (res.ok) {
      onChange(res.data)
      setAwaitingCode(null)
    } else setError(failureMessage(res))
    await onReload()
  }

  const showForm = !prefs.email_verified || changing
  return (
    <Card className="space-y-3 p-5">
      <CardHeader
        icon={<Mail size={22} />}
        title="Avisos por correo"
        right={
          prefs.email_verified && !changing ? (
            <Switch checked={prefs.email_enabled} onChange={(v) => void toggle(v)} label="Recibir avisos por correo" />
          ) : undefined
        }
      />
      {prefs.email_verified && !changing && (
        <>
          <p className="text-[15px]">
            Enviamos los avisos a <strong className="break-all">{prefs.email}</strong>.
          </p>
          <div className="flex gap-2">
            <Button variant="soft" className="flex-1" onClick={() => setChanging(true)}>
              Cambiar correo
            </Button>
            <Button variant="danger" className="flex-1" onClick={() => void remove()}>
              Quitar
            </Button>
          </div>
        </>
      )}
      {showForm && !awaitingCode && (
        <>
          <p className="text-[15px] text-muted">
            Registra tu correo y te enviamos un código de 6 dígitos para confirmarlo.
          </p>
          <Field
            label="Correo"
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="nombre@ejemplo.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Button block disabled={busy || !email.includes('@')} onClick={() => void sendCode()}>
            {busy ? 'Enviando…' : 'Enviar código'}
          </Button>
          {changing && (
            <Button variant="ghost" block onClick={() => setChanging(false)}>
              Cancelar
            </Button>
          )}
        </>
      )}
      {showForm && awaitingCode && (
        <>
          <Notice tone="info">
            Enviamos un código a <strong className="break-all">{awaitingCode}</strong>. Revisa tu bandeja (y el spam).
          </Notice>
          <Field
            label="Código de 6 dígitos"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="000000"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
          />
          <Button block disabled={busy || code.length !== 6} onClick={() => void verify()}>
            {busy ? 'Verificando…' : 'Confirmar correo'}
          </Button>
          <Button variant="ghost" block onClick={() => setAwaitingCode(null)}>
            Usar otro correo
          </Button>
        </>
      )}
      {error && <Notice tone="danger">{error}</Notice>}
    </Card>
  )
}

// --------------------------------------------------------------------------- cuándo

const REMIND_LABEL = (min: number): string => (min === 0 ? 'Sin aviso' : min >= 60 ? `${min / 60} h antes` : `${min} min antes`)

function WhenCard({ prefs, onChange }: { prefs: Preferences; onChange: (p: Preferences) => void }) {
  const [error, setError] = useState<string | null>(null)

  async function save(body: Parameters<typeof notifications.update>[0]): Promise<void> {
    setError(null)
    const res = await notifications.update(body)
    if (res.ok) onChange(res.data)
    else setError(failureMessage(res))
  }

  return (
    <Card className="space-y-4 p-5">
      <h2 className="text-[17px] font-bold">Cuándo avisarme</h2>
      <div>
        <p className="mb-2 text-sm font-semibold">Recordatorio antes de cada visita</p>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Recordatorio antes de cada visita">
          {prefs.remind_options.map((m) => (
            <Chip key={m} selected={prefs.remind_before_min === m} onClick={() => void save({ remind_before_min: m })}>
              {REMIND_LABEL(m)}
            </Chip>
          ))}
        </div>
      </div>
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="font-semibold">Resumen de tu agenda del día</p>
          <p className="text-sm text-muted">Un aviso a la hora que elijas, si tienes visitas.</p>
        </div>
        <Switch checked={prefs.digest_enabled} onChange={(v) => void save({ digest_enabled: v })} label="Resumen del día" />
      </div>
      {prefs.digest_enabled && (
        <Field
          label="Hora del resumen"
          type="time"
          value={prefs.digest_time}
          onChange={(e) => e.target.value && void save({ digest_time: e.target.value })}
        />
      )}
      {error && <Notice tone="danger">{error}</Notice>}
    </Card>
  )
}

// --------------------------------------------------------------------------- prueba

function TestCard({ prefs, onDone }: { prefs: Preferences; onDone: (message: string) => void }) {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const canPush = prefs.push_subscriptions > 0
  const canEmail = prefs.email_verified

  async function send(): Promise<void> {
    setBusy(true)
    setResult(null)
    const res = await notifications.sendTest('all')
    setBusy(false)
    if (!res.ok) {
      setResult(failureMessage(res))
      return
    }
    const r = res.data.results
    const parts = [
      r.push === 'sent' ? 'Enviado al teléfono' : r.push === 'failed' ? 'Falló el aviso al teléfono' : null,
      r.email === 'sent' ? 'Enviado al correo' : r.email === 'failed' ? 'Falló el correo' : null,
    ].filter(Boolean)
    const text = parts.length ? parts.join(' · ') : 'No hay dónde enviar: activa avisos en el teléfono o registra tu correo.'
    setResult(text)
    if (parts.length) onDone(text)
  }

  return (
    <Card className="space-y-3 p-5">
      <h2 className="text-[17px] font-bold">Probar</h2>
      <p className="text-[15px] text-muted">Envía un aviso ahora para comprobar que llega.</p>
      <Button
        variant="soft"
        block
        icon={<Send size={20} />}
        disabled={busy || (!canPush && !canEmail)}
        onClick={() => void send()}
      >
        {busy ? 'Enviando…' : 'Enviar aviso de prueba'}
      </Button>
      {result && <Notice tone="info">{result}</Notice>}
    </Card>
  )
}
