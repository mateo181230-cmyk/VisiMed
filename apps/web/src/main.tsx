import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import { initPwa } from './pwa'
import './styles.css'

initPwa()

// Pide almacenamiento persistente: evita que el sistema borre la cola local si falta espacio
// (doc 02 T2.3 ST3, riesgo R5).
void navigator.storage?.persist?.()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
