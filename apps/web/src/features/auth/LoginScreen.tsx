import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { Button, Field, Notice } from '../../components/ui'
import { useAuth } from './AuthProvider'

export function LoginScreen() {
  const { status, user, needsReauth, signIn } = useAuth()
  const navigate = useNavigate()
  const [phone, setPhone] = useState(user?.phone ?? '')
  const [pin, setPin] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (status === 'loading') return null
  if (status === 'authed' && !needsReauth) return <Navigate to="/" replace />

  async function submit(e: React.FormEvent): Promise<void> {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const message = await signIn(phone, pin)
    setBusy(false)
    if (message) {
      setError(message)
      setPin('')
    } else {
      navigate('/', { replace: true })
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-[480px] flex-col justify-center px-6 pb-10 pt-[calc(24px+var(--safe-top))]">
      <div className="mb-8">
        <h1 className="text-[44px] leading-none font-extrabold tracking-tight text-navy">
          UNO <span className="text-brand">Visitas</span>
        </h1>
        <p className="mt-2 text-lg text-muted">Tu copiloto para la jornada médica</p>
      </div>

      {needsReauth && (
        <Notice tone="warn" className="mb-5">
          Tu sesión venció. Ingresa de nuevo: lo que hiciste sin conexión se conserva y se enviará.
        </Notice>
      )}

      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field
          label="Celular"
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          placeholder="300 123 4567"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
        <Field
          label="PIN de 6 dígitos"
          type="password"
          inputMode="numeric"
          autoComplete="current-password"
          maxLength={6}
          placeholder="••••••"
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
          error={error}
        />
        <Button type="submit" size="lg" block disabled={busy || phone.length < 7 || pin.length !== 6}>
          {busy ? 'Entrando…' : 'Entrar'}
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-muted">
        ¿No tienes usuario o olvidaste tu PIN? Pídeselo a tu administrador.
      </p>
    </main>
  )
}
