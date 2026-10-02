import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { Button, Field, Notice } from '../../components/ui'
import { useAuth } from './AuthProvider'

export function RegisterScreen() {
  const { status, signUp } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [pin, setPin] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (status === 'loading') return null
  if (status === 'authed') return <Navigate to="/" replace />

  async function submit(e: React.FormEvent): Promise<void> {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const message = await signUp(name, phone, email, pin, inviteCode)
    setBusy(false)
    if (message) setError(message)
    else navigate('/', { replace: true })
  }

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-[480px] flex-col justify-center px-6 pb-10 pt-[calc(24px+var(--safe-top))]">
      <div className="mb-7">
        <h1 className="text-[36px] leading-tight font-extrabold text-navy">Crear cuenta</h1>
        <p className="mt-2 text-base text-muted">Registro de visitadores del piloto UNO Visitas</p>
      </div>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Nombre" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} required />
        <Field label="Celular" type="tel" inputMode="tel" autoComplete="tel" placeholder="300 123 4567" value={phone} onChange={(e) => setPhone(e.target.value)} required />
        <Field label="Correo" type="email" inputMode="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <Field label="PIN de 6 dígitos" type="password" inputMode="numeric" autoComplete="new-password" maxLength={6} value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))} required />
        <Field label="Código de invitación" type="password" autoComplete="off" value={inviteCode} onChange={(e) => setInviteCode(e.target.value)} required />
        {error && <Notice tone="danger">{error}</Notice>}
        <Button type="submit" size="lg" block disabled={busy || name.trim().length < 2 || phone.length < 7 || !email.includes('@') || pin.length !== 6 || !inviteCode.trim()}>
          {busy ? 'Creando cuenta…' : 'Crear cuenta'}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        ¿Ya tienes cuenta? <Link to="/login" className="font-semibold text-brand">Entrar</Link>
      </p>
    </main>
  )
}
