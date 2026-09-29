/**
 * Sesión del visitador (doc 01 §10.8).
 *
 * - El token de acceso (24 h) vive en IndexedDB; el de refresco, en una cookie ``httpOnly`` que el
 *   JavaScript no puede leer.
 * - **Lo local no exige autenticación:** con el usuario guardado la app abre directo en *Hoy* aunque
 *   el token haya vencido y no haya red. Al volver la red se refresca y se sube la cola.
 * - Si el refresco falla no se toca la cola: se pide ingresar de nuevo y todo se conserva.
 */
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import {
  type SessionOut,
  type UserOut,
  configureAuthHandlers,
  login,
  logout,
  setAccessToken,
} from '../../api/client'
import { delMeta, getMeta, setMeta, wipeLocalData } from '../../db/db'
import { toE164 } from '../../lib/text'

type Status = 'loading' | 'anon' | 'authed'

interface AuthValue {
  status: Status
  user: UserOut | null
  /** Hay datos locales, pero el servidor ya no reconoce la sesión. */
  needsReauth: boolean
  /** Devuelve un mensaje de error en español, o ``null`` si ingresó. */
  signIn: (phone: string, pin: string) => Promise<string | null>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth debe usarse dentro de <AuthProvider>')
  return ctx
}

async function persist(session: SessionOut): Promise<void> {
  await setMeta('user', session.user)
  await setMeta('session', { access_token: session.access_token, expires_at: session.expires_at })
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [user, setUser] = useState<UserOut | null>(null)
  const [needsReauth, setNeedsReauth] = useState(false)

  useEffect(() => {
    configureAuthHandlers({
      onRefreshed: (session) => {
        void persist(session)
        setUser(session.user)
        setNeedsReauth(false)
      },
      onAuthLost: () => setNeedsReauth(true),
    })
    void (async () => {
      const stored = await getMeta<UserOut>('user')
      const session = await getMeta<{ access_token: string }>('session')
      if (stored) {
        setAccessToken(session?.access_token ?? null)
        setUser(stored)
        setStatus('authed')
      } else {
        setStatus('anon')
      }
    })()
  }, [])

  const signIn = useCallback(async (phone: string, pin: string): Promise<string | null> => {
    const res = await login(toE164(phone), pin)
    if (!res.ok) {
      if (res.kind === 'network') return 'Necesitas conexión para ingresar. Revisa tu señal e inténtalo de nuevo.'
      if (res.kind === 'auth') return 'Celular o PIN incorrectos.'
      if (res.kind === 'server' && res.status === 429) {
        return 'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.'
      }
      if (res.kind === 'client' && res.status === 422) return 'Revisa el celular y el PIN de 6 dígitos.'
      return 'No pudimos ingresar. Inténtalo de nuevo en un momento.'
    }
    const previous = await getMeta<UserOut>('user')
    if (previous && previous.id !== res.data.user.id) await wipeLocalData() // otro visitador en este teléfono
    setAccessToken(res.data.access_token)
    await persist(res.data)
    setUser(res.data.user)
    setNeedsReauth(false)
    setStatus('authed')
    return null
  }, [])

  const signOut = useCallback(async (): Promise<void> => {
    await logout()
    await wipeLocalData()
    await delMeta('session')
    setUser(null)
    setNeedsReauth(false)
    setStatus('anon')
  }, [])

  const value = useMemo(
    () => ({ status, user, needsReauth, signIn, signOut }),
    [status, user, needsReauth, signIn, signOut],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
