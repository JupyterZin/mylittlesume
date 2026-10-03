// WebSocket /ws com reconexão (backoff exponencial com jitter). Ao reconectar, recarrega tudo:
// eventos perdidos durante a queda não são reenviados pelo servidor.
import { getPin } from './lib/storage'
import { useStore } from './store'
import type { WsEvent } from './types'

export function backoffMs(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(30_000, 500 * 2 ** Math.min(attempt, 10))
  return Math.round(base * (0.6 + random() * 0.4))
}

let sock: WebSocket | null = null
let attempt = 0
let timer: ReturnType<typeof setTimeout> | null = null
let everOpened = false
let stopped = false
let lastSeen = Date.now()

function url(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws`
}

function schedule(): void {
  if (stopped || timer) return
  const wait = backoffMs(attempt++)
  timer = setTimeout(() => {
    timer = null
    connect()
  }, wait)
}

export function connect(): void {
  if (stopped) return
  if (sock && (sock.readyState === WebSocket.OPEN || sock.readyState === WebSocket.CONNECTING)) return
  const store = useStore.getState()
  store.setConn('connecting')
  let ws: WebSocket
  try {
    ws = new WebSocket(url())
  } catch {
    schedule()
    return
  }
  sock = ws
  ws.onopen = () => {
    lastSeen = Date.now()
    ws.send(JSON.stringify({ type: 'auth', pin: getPin() ?? '' }))
    attempt = 0
    const s = useStore.getState()
    s.setConn('open')
    // o servidor estava fora no arranque (o service worker serviu o app): arranca agora
    if (s.auth === 'offline') void s.boot()
    else if (everOpened) void s.refreshAll()
    everOpened = true
  }
  ws.onmessage = (msg) => {
    lastSeen = Date.now()
    try {
      const ev = JSON.parse(String(msg.data)) as WsEvent | { type: 'heartbeat' }
      if (ev.type === 'heartbeat') return
      useStore.getState().handle(ev as WsEvent)
    } catch {
      /* mensagem ilegível: ignora */
    }
  }
  ws.onclose = (e) => {
    if (sock === ws) sock = null
    useStore.getState().setConn('closed')
    if (e.code === 4401) {
      useStore.getState().setAuth('pin')
      return
    }
    if (e.code === 4403) {
      useStore.getState().setAuth('forbidden')
      return
    }
    schedule()
  }
}

/** Reconecta já (ex.: o app voltou ao primeiro plano ou a rede voltou). */
export function reconnectNow(): void {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  attempt = 0
  connect()
}

/** O servidor manda um sinal de vida a cada 20 s; sem nada há 45 s, a ligação está morta
 *  (o Android congela o app em segundo plano e não fecha o socket) → reconecta. */
const STALE_MS = 45_000

function checkStale(): void {
  if (sock && sock.readyState === WebSocket.OPEN && Date.now() - lastSeen > STALE_MS) {
    const dead = sock
    sock = null
    dead.onclose = null
    try {
      dead.close()
    } catch {
      /* já estava fechado */
    }
    useStore.getState().setConn('closed')
    reconnectNow()
  }
}

export function startLive(): () => void {
  stopped = false
  connect()
  const onVisible = () => {
    if (document.visibilityState !== 'visible') return
    // voltou ao primeiro plano: busca o que chegou entretanto e confirma que a ligação está viva
    void useStore.getState().refreshAll()
    if (!sock) reconnectNow()
    else checkStale()
  }
  const watchdog = window.setInterval(checkStale, 10_000)
  document.addEventListener('visibilitychange', onVisible)
  window.addEventListener('online', reconnectNow)
  window.addEventListener('focus', onVisible)
  return () => {
    stopped = true
    window.clearInterval(watchdog)
    document.removeEventListener('visibilitychange', onVisible)
    window.removeEventListener('online', reconnectNow)
    window.removeEventListener('focus', onVisible)
    sock?.close()
  }
}
