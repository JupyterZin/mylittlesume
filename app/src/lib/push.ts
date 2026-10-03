// Notificações Web Push neste aparelho: estado, ligar/desligar, teste e ressincronização no arranque.
// O servidor guarda as inscrições (/api/push/*); aqui só fica a intenção do Lucas ('talos.push') e o
// último endpoint enviado (para o servidor trocar o antigo se o navegador o rodar).
import { api, ApiError } from '../api'
import { load, save } from './storage'

export type PushStatus = 'unsupported' | 'blocked' | 'off' | 'on'

export interface PushEnv {
  supported: boolean
  permission: NotificationPermission
  subscribed: boolean
}

export class PushFailure extends Error {}

const PREF = 'talos.push'
const ENDPOINT = 'talos.push.endpoint'
const READY_TIMEOUT_MS = 10_000
const SUBSCRIBE_TIMEOUT_MS = 20_000

// ------------------------------------------------------------------ puras (testadas no vitest)
/** chave VAPID (base64url, sem padding) → bytes para `applicationServerKey` */
export function urlBase64ToUint8Array(b64: string): Uint8Array<ArrayBuffer> {
  const clean = b64.trim().replace(/=+$/, '')
  if (!/^[A-Za-z0-9_-]*$/.test(clean)) throw new PushFailure('Chave do servidor ilegível.')
  const std = clean.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (clean.length % 4)) % 4)
  const bin = atob(std)
  const out = new Uint8Array(new ArrayBuffer(bin.length))
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

export function bufferToUrlBase64(buf: ArrayBuffer | ArrayBufferView | null | undefined): string {
  if (!buf) return ''
  const bytes = buf instanceof ArrayBuffer ? new Uint8Array(buf) : new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength)
  let bin = ''
  for (const b of bytes) bin += String.fromCharCode(b)
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** a inscrição atual foi feita com a chave que o servidor usa hoje? (se o cofre mudou, não) */
export function sameKey(current: ArrayBuffer | null | undefined, serverKey: string): boolean {
  return !!current && bufferToUrlBase64(current) === serverKey.replace(/=+$/, '')
}

export function statusFrom(env: PushEnv): PushStatus {
  if (!env.supported) return 'unsupported'
  if (env.permission === 'denied') return 'blocked'
  return env.permission === 'granted' && env.subscribed ? 'on' : 'off'
}

export interface SubscriptionBody {
  endpoint: string
  keys: { p256dh: string; auth: string }
  old_endpoint?: string | null
}

export function subscriptionBody(json: PushSubscriptionJSON, oldEndpoint?: string | null): SubscriptionBody {
  const p256dh = json.keys?.p256dh
  const auth = json.keys?.auth
  if (!json.endpoint || !p256dh || !auth) throw new PushFailure('O navegador devolveu uma inscrição incompleta.')
  const body: SubscriptionBody = { endpoint: json.endpoint, keys: { p256dh, auth } }
  if (oldEndpoint && oldEndpoint !== json.endpoint) body.old_endpoint = oldEndpoint
  return body
}

export function pushErrorMessage(e: unknown): string {
  if (e instanceof PushFailure || e instanceof ApiError) return e.message
  const name = (e as { name?: string } | null)?.name
  if (name === 'NotAllowedError') return 'As notificações estão bloqueadas para o Talos neste aparelho.'
  if (name === 'AbortError') return 'O serviço de notificações do navegador não respondeu. Tente de novo em instantes.'
  if (name === 'InvalidStateError') return 'O app ainda está iniciando. Tente de novo em instantes.'
  return 'Não foi possível mudar as notificações.'
}

/** Só caminhos do próprio app (o service worker manda o destino ao tocar na notificação). */
export function appPath(url: unknown): string | null {
  return typeof url === 'string' && url.startsWith('/') && !url.startsWith('//') ? url : null
}

// ------------------------------------------------------------------ navegador
function supported(): boolean {
  const g = globalThis as { isSecureContext?: boolean; navigator?: Navigator; PushManager?: unknown; Notification?: unknown }
  return !!g.isSecureContext && !!g.navigator && 'serviceWorker' in g.navigator && !!g.PushManager && !!g.Notification
}

async function withTimeout<T>(work: Promise<T>, ms: number, message: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new PushFailure(message)), ms)
  })
  try {
    return await Promise.race([work, timeout])
  } finally {
    clearTimeout(timer)
  }
}

function registration(timeoutMs = READY_TIMEOUT_MS): Promise<ServiceWorkerRegistration> {
  return withTimeout(
    navigator.serviceWorker.ready,
    timeoutMs,
    'O service worker do app não está ativo. Feche e abra o app e tente de novo.',
  )
}

export async function pushEnv(): Promise<PushEnv> {
  if (!supported()) return { supported: false, permission: 'default', subscribed: false }
  const permission = Notification.permission
  let subscribed = false
  if (permission === 'granted') {
    try {
      const reg = await registration(3_000)
      subscribed = !!(await reg.pushManager.getSubscription())
    } catch {
      subscribed = false
    }
  }
  return { supported: true, permission, subscribed }
}

export async function readPushStatus(): Promise<PushStatus> {
  return statusFrom(await pushEnv())
}

async function subscribeWithServerKey(reg: ServiceWorkerRegistration): Promise<PushSubscription> {
  const { public_key } = await api.pushKey()
  let sub = await reg.pushManager.getSubscription()
  if (sub && !sameKey(sub.options.applicationServerKey, public_key)) {
    await sub.unsubscribe() // feita com outra chave VAPID: o servidor já não consegue usá-la
    sub = null
  }
  if (sub) return sub
  // sem serviço de push (ex.: Chrome sem os serviços do Google) o pedido pode ficar pendurado
  return withTimeout(
    reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(public_key) }),
    SUBSCRIBE_TIMEOUT_MS,
    'O serviço de notificações do navegador não respondeu. Tente de novo em instantes.',
  )
}

async function register(sub: PushSubscription): Promise<void> {
  await api.pushSubscribe(subscriptionBody(sub.toJSON(), load(ENDPOINT)))
  save(ENDPOINT, sub.endpoint)
}

/** Ligar (a partir de um toque: o pedido de permissão precisa de um gesto do Lucas). */
export async function enablePush(): Promise<PushStatus> {
  if (!supported()) throw new PushFailure('Este navegador não suporta notificações push.')
  const permission = await Notification.requestPermission()
  if (permission === 'denied') {
    throw new PushFailure('As notificações estão bloqueadas. Libere nas configurações do Chrome (Configurações do site → Notificações).')
  }
  if (permission !== 'granted') throw new PushFailure('Permissão não concedida.')
  const reg = await registration()
  await register(await subscribeWithServerKey(reg))
  save(PREF, 'on')
  return 'on'
}

export async function disablePush(): Promise<PushStatus> {
  save(PREF, 'off')
  if (!supported()) return 'unsupported'
  const reg = await registration()
  const sub = await reg.pushManager.getSubscription()
  if (sub) {
    try {
      await api.pushUnsubscribe(sub.endpoint)
    } catch {
      /* sem ligação: o servidor apaga-a sozinho quando o serviço de push responder 410 */
    }
    await sub.unsubscribe()
  }
  save(ENDPOINT, null)
  return statusFrom(await pushEnv())
}

/** No arranque: se o Lucas ligou neste aparelho, garante que o servidor tem a inscrição certa
 *  (o endpoint pode rodar; a chave VAPID pode ter mudado). Nunca pede permissão sozinho. */
export async function syncPush(): Promise<void> {
  if (!supported() || Notification.permission !== 'granted' || load(PREF) === 'off') return
  try {
    const reg = await registration()
    const existing = await reg.pushManager.getSubscription()
    if (!existing && load(PREF) !== 'on') return
    await register(await subscribeWithServerKey(reg))
  } catch (e) {
    console.warn('talos: não consegui sincronizar as notificações', e)
  }
}

export async function sendTestPush(): Promise<{ ok: boolean; sent: number; failed: number; removed: number }> {
  return api.pushTest()
}

/** Fecha notificações já mostradas (ex.: cartão decidido no app; app aberto lê as mensagens). */
export async function closeNotifications(match: (n: Notification) => boolean): Promise<void> {
  if (!supported()) return
  try {
    const reg = await navigator.serviceWorker.getRegistration()
    for (const n of (await reg?.getNotifications()) ?? []) if (match(n)) n.close()
  } catch {
    /* sem service worker: nada a fechar */
  }
}

export function notificationKind(n: Notification): string {
  const data = n.data as { kind?: unknown } | null
  return typeof data?.kind === 'string' ? data.kind : ''
}

/** Toque numa notificação com o app já aberto: o service worker pede para navegar até ao destino. */
export function listenNotificationClicks(go: (path: string) => void): () => void {
  if (!supported()) return () => undefined
  const onMessage = (e: MessageEvent) => {
    const data = e.data as { type?: unknown; url?: unknown } | null
    const path = data?.type === 'talos:navigate' ? appPath(data.url) : null
    if (path) go(path)
  }
  navigator.serviceWorker.addEventListener('message', onMessage)
  return () => navigator.serviceWorker.removeEventListener('message', onMessage)
}
