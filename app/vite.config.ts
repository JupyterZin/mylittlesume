import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// Em desenvolvimento, o core roda em 127.0.0.1:8000 (make dev) e o noVNC em 127.0.0.1:6080.
const CORE = process.env.TALOS_CORE_URL ?? 'http://127.0.0.1:8000'
const TELA = process.env.TALOS_TELA_URL ?? 'http://127.0.0.1:6080'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: false,
      includeAssets: ['favicon.svg', 'icons/apple-touch-icon.png'],
      manifest: {
        name: 'Talos',
        short_name: 'Talos',
        description: 'O seu agente pessoal.',
        lang: 'pt-BR',
        dir: 'ltr',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#13302E',
        theme_color: '#13302E',
        categories: ['productivity'],
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2,glb,webmanifest}'],
        globIgnores: ['poses/**', '**/*vietnamese*'],
        maximumFileSizeToCacheInBytes: 6 * 1024 * 1024,
        navigateFallback: '/index.html',
        // a API, o WebSocket e a Tela (noVNC, servida pelo tailscale serve) nunca passam pelo app
        navigateFallbackDenylist: [/^\/api\//, /^\/ws/, /^\/tela/, /^\/health/],
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith('/poses/'),
            handler: 'CacheFirst',
            options: { cacheName: 'talos-poses', expiration: { maxEntries: 40 } },
          },
        ],
      },
    }),
  ],
  build: {
    assetsDir: 'static', // ficheiros com hash: o core serve-os com cache imutável
    target: 'es2022',
    chunkSizeWarningLimit: 1600,
  },
  server: {
    proxy: {
      '/api': CORE,
      '/health': CORE,
      '/ws': { target: CORE.replace(/^http/, 'ws'), ws: true },
      '/tela': { target: TELA, rewrite: (p) => p.replace(/^\/tela/, ''), ws: true },
    },
  },
})
