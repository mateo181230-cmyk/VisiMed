/**
 * Ciclo de vida de la PWA: registro del service worker, aviso de «Nueva versión» e instalación.
 *
 * La nueva versión se descarga en segundo plano y solo se activa cuando el usuario lo pide. Cuando
 * exista la visita «en curso» (módulo Llegué/Terminé) el aviso se ocultará mientras haya una
 * (doc 02 T2.2 ST6).
 */
import { useSyncExternalStore } from 'react'
import { registerSW } from 'virtual:pwa-register'

let needRefresh = false
let updateSW: ((reloadPage?: boolean) => Promise<void>) | null = null
const listeners = new Set<() => void>()
const notify = (): void => listeners.forEach((fn) => fn())

export function initPwa(): void {
  updateSW = registerSW({
    immediate: true,
    onNeedRefresh() {
      needRefresh = true
      notify()
    },
  })
}

export function usePwaUpdate(): { needRefresh: boolean; update: () => void } {
  const value = useSyncExternalStore(
    (fn) => {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
    () => needRefresh,
    () => false,
  )
  return { needRefresh: value, update: () => void updateSW?.(true) }
}

// --- instalación (Android/Chrome: botón «Instalar»; iPhone: guía de 3 pasos)

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

let deferred: BeforeInstallPromptEvent | null = null
const installListeners = new Set<() => void>()

if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault()
    deferred = e as BeforeInstallPromptEvent
    installListeners.forEach((fn) => fn())
  })
  window.addEventListener('appinstalled', () => {
    deferred = null
    installListeners.forEach((fn) => fn())
  })
}

export function useInstallPrompt(): { canInstall: boolean; install: () => Promise<void> } {
  const canInstall = useSyncExternalStore(
    (fn) => {
      installListeners.add(fn)
      return () => installListeners.delete(fn)
    },
    () => deferred !== null,
    () => false,
  )
  return {
    canInstall,
    install: async () => {
      if (!deferred) return
      await deferred.prompt()
      await deferred.userChoice
      deferred = null
      installListeners.forEach((fn) => fn())
    },
  }
}
