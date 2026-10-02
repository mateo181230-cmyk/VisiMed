/// <reference lib="webworker" />
/**
 * Service worker de UNO Visitas (doc 02 T2.2):
 *  - precachea toda la app: abre sin red desde la 2.ª apertura;
 *  - responde a las navegaciones con ``index.html`` (SPA), salvo las rutas de la API;
 *  - muestra los avisos push y abre la app al tocarlos.
 */
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'

declare const self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: Array<{ url: string; revision: string | null }>
}

precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()

// Una compilación para presentar puede reemplazar la caché anterior si solo hay pantallas
// de presentación o consulta abiertas. No la adelanta en una visita ni al editar entrenamiento.
// Las compilaciones normales conservan el botón «Actualizar» como única forma de activarla.
self.addEventListener('install', (event) => {
  if ((import.meta as ImportMeta & { env: { VITE_DEMO_PREVIEW?: string } }).env.VITE_DEMO_PREVIEW !== 'true') return
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    const safe = windows.length > 0 && windows.every(client => {
      const path = new URL(client.url).pathname
      return path === '/login' || path === '/admin' || path === '/inteligencia' || path === '/inteligencia/resumen' || path.startsWith('/admin/training/demo') || path.startsWith('/inteligencia/demo')
    })
    if (safe) await self.skipWaiting()
  })())
})

registerRoute(
  new NavigationRoute(createHandlerBoundToURL('/index.html'), {
    denylist: [/^\/v1\//, /^\/salud/],
  }),
)

// La nueva versión espera a que el usuario toque «Actualizar».
self.addEventListener('message', (event) => {
  if ((event.data as { type?: string } | undefined)?.type === 'SKIP_WAITING') void self.skipWaiting()
})
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

// ---------------------------------------------------------------------------------- push

interface PushPayload {
  title?: string
  body?: string
  url?: string
  tag?: string | null
  kind?: string
}

self.addEventListener('push', (event) => {
  let data: PushPayload = {}
  try {
    data = (event.data?.json() ?? {}) as PushPayload
  } catch {
    data = { body: event.data?.text() }
  }
  const title = data.title || 'UNO Visitas'
  const options: NotificationOptions & { renotify?: boolean } = {
    body: data.body ?? '',
    icon: '/icons/icon-192.png',
    badge: '/icons/badge-72.png',
    tag: data.tag ?? undefined,
    renotify: Boolean(data.tag),
    data: { url: data.url || '/' },
    lang: 'es-CO',
  }
  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL((event.notification.data as { url?: string } | undefined)?.url ?? '/', self.location.origin).href
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const client of windows) {
        if (new URL(client.url).origin === self.location.origin && 'focus' in client) {
          await client.focus()
          if ('navigate' in client) await (client as WindowClient).navigate(target).catch(() => undefined)
          return
        }
      }
      await self.clients.openWindow(target)
    })(),
  )
})
