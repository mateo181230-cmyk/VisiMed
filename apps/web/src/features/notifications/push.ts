/**
 * Web Push en el navegador (RFC 8030 / 8292). Este módulo solo toca APIs del navegador; el
 * servidor recibe la suscripción por ``POST /v1/notifications/push/subscriptions``.
 *
 * Notas de plataforma (doc 01 §8.5):
 * - iPhone: las notificaciones web solo funcionan con la app **instalada** en la pantalla de
 *   inicio (iOS ≥ 16.4). Desde Safari sin instalar no existe ``PushManager``.
 * - Android/Chrome: funcionan desde el navegador o instalada.
 */

export type PushSupport =
  | 'unsupported' // el navegador no puede recibir avisos
  | 'needs-install' // iPhone/iPad: hay que instalar la app primero
  | 'denied' // el usuario los bloqueó en el navegador
  | 'default' // se puede pedir el permiso
  | 'granted' // permiso concedido

function isIos(): boolean {
  const ua = navigator.userAgent
  return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

export function isStandalone(): boolean {
  return (
    window.matchMedia?.('(display-mode: standalone)').matches === true ||
    (navigator as unknown as { standalone?: boolean }).standalone === true
  )
}

export function pushSupport(): PushSupport {
  const capable = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
  if (!capable) return isIos() && !isStandalone() ? 'needs-install' : 'unsupported'
  if (Notification.permission === 'denied') return 'denied'
  return Notification.permission === 'granted' ? 'granted' : 'default'
}

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'))
  const out = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

async function registration(): Promise<ServiceWorkerRegistration> {
  const reg = await navigator.serviceWorker.getRegistration()
  if (reg) return reg
  // En desarrollo el service worker puede no estar activo todavía.
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error('El service worker no está activo. Instala o recarga la app.')), 8000),
    ),
  ])
}

export interface DeviceSubscription {
  endpoint: string
  p256dh: string
  auth: string
}

function toDevice(sub: PushSubscription): DeviceSubscription {
  const json = sub.toJSON()
  return {
    endpoint: sub.endpoint,
    p256dh: json.keys?.p256dh ?? '',
    auth: json.keys?.auth ?? '',
  }
}

/** Suscripción actual de este dispositivo, si existe. */
export async function currentSubscription(): Promise<DeviceSubscription | null> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return null
  const reg = await navigator.serviceWorker.getRegistration()
  const sub = await reg?.pushManager.getSubscription()
  return sub ? toDevice(sub) : null
}

/** Pide el permiso y suscribe este dispositivo. Lanza un ``Error`` con mensaje en español. */
export async function enablePush(vapidPublicKey: string): Promise<DeviceSubscription> {
  if (pushSupport() === 'needs-install') {
    throw new Error('En iPhone primero instala la app: Compartir → Agregar a pantalla de inicio.')
  }
  if (pushSupport() === 'unsupported') {
    throw new Error('Este navegador no puede recibir avisos.')
  }
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    throw new Error('No diste permiso. Puedes activarlo después en los ajustes del navegador.')
  }
  const reg = await registration()
  const existing = await reg.pushManager.getSubscription()
  const sub =
    existing ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
    }))
  const device = toDevice(sub)
  if (!device.p256dh || !device.auth) throw new Error('El navegador no devolvió las llaves de la suscripción.')
  return device
}

/** Da de baja la suscripción de este dispositivo y devuelve su ``endpoint`` (para avisar al servidor). */
export async function disablePush(): Promise<string | null> {
  const reg = await navigator.serviceWorker.getRegistration()
  const sub = await reg?.pushManager.getSubscription()
  if (!sub) return null
  const { endpoint } = sub
  await sub.unsubscribe()
  return endpoint
}
