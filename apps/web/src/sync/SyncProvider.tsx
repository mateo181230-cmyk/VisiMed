import { useLiveQuery } from 'dexie-react-hooks'
import { type ReactNode, createContext, useContext, useEffect, useSyncExternalStore } from 'react'
import { fetchState, postSync } from '../api/client'
import { db } from '../db/db'
import { useAuth } from '../features/auth/AuthProvider'
import { type EngineState, SyncEngine } from './engine'

const engine = new SyncEngine({ postSync, fetchState })
const EngineContext = createContext<SyncEngine>(engine)

export function useEngine(): SyncEngine {
  return useContext(EngineContext)
}

/** Arranca el motor mientras haya un usuario y lo detiene al cerrar sesión. */
export function SyncProvider({ children }: { children: ReactNode }) {
  const { status, needsReauth } = useAuth()

  useEffect(() => {
    if (status !== 'authed') return
    void engine.start()
    return () => engine.stop()
  }, [status])

  useEffect(() => {
    if (status === 'authed' && !needsReauth) void engine.run(true)
  }, [status, needsReauth])

  return <EngineContext.Provider value={engine}>{children}</EngineContext.Provider>
}

export function useEngineState(): EngineState {
  const e = useEngine()
  return useSyncExternalStore(e.subscribe, e.getState, e.getState)
}

export interface OutboxCounts {
  pending: number
  rejected: number
  expired: number
}

export function useOutboxCounts(): OutboxCounts {
  return (
    useLiveQuery(async () => {
      const rows = await db.outbox.toArray()
      const count = (statuses: string[]): number => rows.filter((r) => statuses.includes(r.status)).length
      return {
        pending: count(['pending', 'sending']),
        rejected: count(['rejected']),
        expired: count(['expired']),
      }
    }, []) ?? { pending: 0, rejected: 0, expired: 0 }
  )
}

/** Estado de la conexión del navegador (solo informativo; nunca bloquea). */
export function useOnline(): boolean {
  return useSyncExternalStore(
    (fn) => {
      window.addEventListener('online', fn)
      window.addEventListener('offline', fn)
      return () => {
        window.removeEventListener('online', fn)
        window.removeEventListener('offline', fn)
      }
    },
    () => navigator.onLine,
    () => true,
  )
}
