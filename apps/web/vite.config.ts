import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { defineConfig } from 'vitest/config'

// La API corre en :8000 (uvicorn). El proxy mantiene el mismo origen, así la cookie de refresco
// (httpOnly, SameSite=Strict) funciona igual en desarrollo y en producción.
const apiTarget = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000'
const previewAllowedHosts = (process.env.VITE_PREVIEW_ALLOWED_HOSTS ?? '').split(',').map((host) => host.trim()).filter(Boolean)
const proxy = {
  '/v1': { target: apiTarget, changeOrigin: false },
  '/salud': { target: apiTarget, changeOrigin: false },
}

export default defineConfig({
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      registerType: 'prompt',
      injectRegister: false,
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2,webmanifest}'],
        // También se guarda el pequeño cliente de Daily: una PWA con la versión anterior
        // debe poder cargar su chunk mientras instala la actualización. La llamada exige red.
      },
      manifest: {
        name: 'UNO Visitas',
        short_name: 'UNO',
        description: 'Tu copiloto para la jornada médica',
        lang: 'es-CO',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#f4f7fb',
        theme_color: '#1668f0',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy, allowedHosts: previewAllowedHosts },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
