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
    ws.send(JSON.stringify({ type: 'auth', pin: getPin() ?? '' }))
    attempt = 0
    useStore.getState().setConn('open')
    if (everOpened) void useStore.getState().refreshAll()
    everOpened = true
  }
  ws.onmessage = (msg) => {
    try {
      useStore.getState().handle(JSON.parse(String(msg.data)) as WsEvent)
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

export function startLive(): () => void {
  stopped = false
  connect()
  const onVisible = () => {
    if (document.visibilityState === 'visible' && !sock) reconnectNow()
  }
  document.addEventListener('visibilitychange', onVisible)
  window.addEventListener('online', reconnectNow)
  return () => {
    stopped = true
    document.removeEventListener('visibilitychange', onVisible)
    window.removeEventListener('online', reconnectNow)
    sock?.close()
  }
}
