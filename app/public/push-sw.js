/* Talos · notificações Web Push no service worker.
 *
 * Carregado pelo service worker gerado pelo Workbox (vite.config.ts → workbox.importScripts).
 * O servidor manda {title, body, url, tag, kind, silent?, ts} (já redigido e cortado).
 *
 * Segurança: a notificação NÃO tem botão "aprovar". Tocar só abre o app no cartão completo,
 * para o Lucas ver exatamente o que vai sair antes de decidir.
 */
/* eslint-disable no-restricted-globals */

const TALOS_ICON = '/icons/icon-192.png'
const TALOS_BADGE = '/icons/badge-96.png'

function talosPath(url) {
  // só caminhos do próprio app; qualquer outra coisa abre a conversa
  if (typeof url !== 'string' || !url.startsWith('/') || url.startsWith('//')) return '/'
  return url
}

async function talosWindows() {
  const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
  const mine = all.filter((c) => new URL(c.url).origin === self.location.origin)
  // primeiro a janela que está à frente, depois as visíveis, depois o resto
  const rank = (c) => (c.focused ? 0 : c.visibilityState === 'visible' ? 1 : 2)
  return mine.sort((a, b) => rank(a) - rank(b))
}

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = { body: event.data ? event.data.text() : '' }
  }
  event.waitUntil(
    (async () => {
      const wins = await talosWindows()
      // com o app aberto à frente, a notificação fica na gaveta mas não toca nem vibra
      const onScreen = wins.some((c) => c.focused && c.visibilityState === 'visible')
      const silent = Boolean(data.silent) || onScreen
      const tag = typeof data.tag === 'string' && data.tag ? data.tag : undefined
      await self.registration.showNotification(data.title || 'Talos', {
        body: data.body || '',
        icon: TALOS_ICON,
        badge: TALOS_BADGE,
        tag,
        renotify: Boolean(tag) && !silent, // mesmo cartão de novo (lembrete): volta a avisar
        silent,
        timestamp: typeof data.ts === 'number' ? data.ts : Date.now(),
        lang: 'pt-BR',
        dir: 'ltr',
        data: { url: talosPath(data.url), kind: data.kind || 'notice' },
      })
    })(),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const path = talosPath(event.notification.data && event.notification.data.url)
  event.waitUntil(
    (async () => {
      for (const c of await talosWindows()) {
        try {
          const focused = await c.focus()
          // o app navega sozinho (sem recarregar o 3D nem cair o WebSocket)
          ;(focused || c).postMessage({ type: 'talos:navigate', url: path })
          return
        } catch {
          /* janela que já não deixa focar: tenta a próxima */
        }
      }
      await self.clients.openWindow(path)
    })(),
  )
})

// O navegador trocou a inscrição (raro no Android): reinscreve e avisa o servidor. Sem PIN no
// service worker isto pode falhar (401); o app volta a sincronizar quando for aberto.
self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil(
    (async () => {
      const old = event.oldSubscription
      let sub = event.newSubscription
      if (!sub) {
        const key = old && old.options && old.options.applicationServerKey
        if (!key) return
        sub = await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key })
      }
      await fetch('/api/push/subscribe', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ ...sub.toJSON(), old_endpoint: old ? old.endpoint : null }),
      })
    })().catch(() => undefined),
  )
})
