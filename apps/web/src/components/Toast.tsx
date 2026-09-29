import { type ReactNode, createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'

interface ToastApi {
  show: (message: string) => void
}

const ToastContext = createContext<ToastApi>({ show: () => {} })

export function useToast(): ToastApi {
  return useContext(ToastContext)
}

/** Aviso breve y discreto sobre la barra inferior. Nunca bloquea. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const show = useCallback((text: string) => {
    setMessage(text)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setMessage(null), 3200)
  }, [])

  const api = useMemo(() => ({ show }), [show])
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-[calc(84px+var(--safe-bottom))] z-[60] flex justify-center px-4"
      >
        {message && (
          <div className="pointer-events-auto max-w-[440px] animate-[fade-in_.15s_ease-out] rounded-control bg-ink px-4 py-3 text-[15px] font-medium text-white shadow-lg">
            {message}
          </div>
        )}
      </div>
    </ToastContext.Provider>
  )
}
