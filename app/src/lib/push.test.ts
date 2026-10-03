import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api'
import {
  appPath,
  bufferToUrlBase64,
  disablePush,
  enablePush,
  PushFailure,
  pushErrorMessage,
  sameKey,
  statusFrom,
  subscriptionBody,
  syncPush,
  urlBase64ToUint8Array,
} from './push'

// chave VAPID pública de exemplo (65 bytes, começa por 0x04)
const KEY = 'BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U'
const OTHER = 'BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM'

describe('urlBase64ToUint8Array / bufferToUrlBase64', () => {
  it('decodifica a chave VAPID do servidor', () => {
    const bytes = urlBase64ToUint8Array(KEY)
    expect(bytes.length).toBe(65)
    expect(bytes[0]).toBe(4)
    expect(bytes.buffer).toBeInstanceOf(ArrayBuffer)
    expect(bufferToUrlBase64(bytes)).toBe(KEY)
    expect(bufferToUrlBase64(bytes.buffer)).toBe(KEY)
  })

  it('aceita base64url com ou sem padding e com - e _', () => {
    expect([...urlBase64ToUint8Array('-_8')]).toEqual([0xfb, 0xff])
    expect([...urlBase64ToUint8Array('-_8=')]).toEqual([0xfb, 0xff])
    expect([...urlBase64ToUint8Array('AQID')]).toEqual([1, 2, 3])
    expect([...urlBase64ToUint8Array(' AQ ')]).toEqual([1])
    expect(bufferToUrlBase64(new Uint8Array([0xfb, 0xff]))).toBe('-_8')
    expect(bufferToUrlBase64(null)).toBe('')
  })

  it('recusa base64 normal (+ e /) e lixo', () => {
    expect(() => urlBase64ToUint8Array('+/8=')).toThrow(PushFailure)
    expect(() => urlBase64ToUint8Array('não é chave')).toThrow(PushFailure)
  })

  it('compara a chave da inscrição com a do servidor', () => {
    const buf = urlBase64ToUint8Array(KEY).buffer
    expect(sameKey(buf, KEY)).toBe(true)
    expect(sameKey(buf, `${KEY}=`)).toBe(true)
    expect(sameKey(buf, OTHER)).toBe(false)
    expect(sameKey(null, KEY)).toBe(false)
  })
})

describe('estado e mensagens', () => {
  it('não suportado / bloqueado / desligado / ligado', () => {
    expect(statusFrom({ supported: false, permission: 'granted', subscribed: true })).toBe('unsupported')
    expect(statusFrom({ supported: true, permission: 'denied', subscribed: false })).toBe('blocked')
    expect(statusFrom({ supported: true, permission: 'default', subscribed: false })).toBe('off')
    expect(statusFrom({ supported: true, permission: 'granted', subscribed: false })).toBe('off')
    expect(statusFrom({ supported: true, permission: 'granted', subscribed: true })).toBe('on')
  })

  it('monta o corpo do POST e só manda o endpoint antigo se mudou', () => {
    const json = { endpoint: 'https://fcm.googleapis.com/fcm/send/a', keys: { p256dh: 'P', auth: 'A' } }
    expect(subscriptionBody(json)).toEqual({ endpoint: json.endpoint, keys: { p256dh: 'P', auth: 'A' } })
    expect(subscriptionBody(json, json.endpoint).old_endpoint).toBeUndefined()
    expect(subscriptionBody(json, 'https://fcm.googleapis.com/fcm/send/velho').old_endpoint).toBe(
      'https://fcm.googleapis.com/fcm/send/velho',
    )
    expect(() => subscriptionBody({ endpoint: json.endpoint, keys: { p256dh: 'P' } })).toThrow(PushFailure)
  })

  it('erros em português', () => {
    expect(pushErrorMessage({ name: 'NotAllowedError' })).toMatch(/bloqueadas/)
    expect(pushErrorMessage({ name: 'AbortError' })).toMatch(/não respondeu/)
    expect(pushErrorMessage(new ApiError(400, 'serviço de push não reconhecido: x'))).toBe('serviço de push não reconhecido: x')
    expect(pushErrorMessage(new Error('boom'))).toBe('Não foi possível mudar as notificações.')
  })

  it('só navega para caminhos do próprio app', () => {
    expect(appPath('/aprovacoes/12')).toBe('/aprovacoes/12')
    expect(appPath('//evil.example')).toBeNull()
    expect(appPath('https://evil.example')).toBeNull()
    expect(appPath(42)).toBeNull()
  })
})

// ------------------------------------------------------------------ fluxo com navegador falso
interface FakeSub {
  endpoint: string
  options: { applicationServerKey: ArrayBuffer | null }
  toJSON: () => PushSubscriptionJSON
  unsubscribe: ReturnType<typeof vi.fn>
}

function fakeSub(endpoint: string, key: string): FakeSub {
  return {
    endpoint,
    options: { applicationServerKey: urlBase64ToUint8Array(key).buffer },
    toJSON: () => ({ endpoint, keys: { p256dh: 'BROWSER-P256DH', auth: 'BROWSER-AUTH' } }),
    unsubscribe: vi.fn(async () => true),
  }
}

function setup(opts: { permission?: NotificationPermission; answer?: NotificationPermission; current?: FakeSub | null } = {}) {
  const store = new Map<string, string>()
  const calls: { method: string; path: string; body: unknown }[] = []
  let current: FakeSub | null = opts.current ?? null
  const subscribe = vi.fn(async (o: { userVisibleOnly: boolean; applicationServerKey: Uint8Array }) => {
    current = fakeSub('https://fcm.googleapis.com/fcm/send/novo', bufferToUrlBase64(o.applicationServerKey))
    return current
  })
  const reg = { pushManager: { getSubscription: vi.fn(async () => current), subscribe } }
  const notification = {
    permission: opts.permission ?? 'default',
    requestPermission: vi.fn(async () => {
      notification.permission = opts.answer ?? 'granted'
      return notification.permission
    }),
  }
  vi.stubGlobal('isSecureContext', true)
  vi.stubGlobal('PushManager', function PushManager() {})
  vi.stubGlobal('Notification', notification)
  vi.stubGlobal('navigator', { serviceWorker: { ready: Promise.resolve(reg) } })
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init: RequestInit) => {
      const body = init.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method: init.method ?? 'GET', path, body })
      const json =
        path === '/api/push/key'
          ? { public_key: KEY, enabled: true, subscriptions: 0 }
          : { ok: true, created: true, removed: true, subscriptions: 1 }
      return new Response(JSON.stringify(json), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  return { store, calls, reg, subscribe, notification, sub: () => current }
}

describe('ligar, desligar e ressincronizar', () => {
  beforeEach(() => vi.unstubAllGlobals())
  afterEach(() => vi.unstubAllGlobals())

  it('ligar pede permissão, inscreve com a chave do servidor e manda a inscrição', async () => {
    const f = setup()
    expect(await enablePush()).toBe('on')
    expect(f.notification.requestPermission).toHaveBeenCalledOnce()
    const opts = f.subscribe.mock.calls[0][0]
    expect(opts.userVisibleOnly).toBe(true)
    expect(bufferToUrlBase64(opts.applicationServerKey)).toBe(KEY)
    const post = f.calls.find((c) => c.method === 'POST')
    expect(post?.path).toBe('/api/push/subscribe')
    expect(post?.body).toEqual({
      endpoint: 'https://fcm.googleapis.com/fcm/send/novo',
      keys: { p256dh: 'BROWSER-P256DH', auth: 'BROWSER-AUTH' },
    })
    expect(f.store.get('talos.push')).toBe('on')
  })

  it('permissão negada: não inscreve e explica', async () => {
    const f = setup({ answer: 'denied' })
    await expect(enablePush()).rejects.toThrow(/bloqueadas/)
    expect(f.subscribe).not.toHaveBeenCalled()
    expect(f.calls).toEqual([])
  })

  it('no arranque troca a inscrição feita com uma chave antiga e avisa o endpoint velho', async () => {
    const old = fakeSub('https://fcm.googleapis.com/fcm/send/velho', OTHER)
    const f = setup({ permission: 'granted', current: old })
    f.store.set('talos.push', 'on')
    f.store.set('talos.push.endpoint', old.endpoint)
    await syncPush()
    expect(old.unsubscribe).toHaveBeenCalledOnce()
    expect(f.subscribe).toHaveBeenCalledOnce()
    const post = f.calls.find((c) => c.method === 'POST')
    expect(post?.body).toMatchObject({ endpoint: 'https://fcm.googleapis.com/fcm/send/novo', old_endpoint: old.endpoint })
  })

  it('no arranque não faz nada se o Lucas desligou ou nunca deu permissão', async () => {
    let f = setup({ permission: 'granted', current: fakeSub('https://fcm.googleapis.com/fcm/send/a', KEY) })
    f.store.set('talos.push', 'off')
    await syncPush()
    expect(f.calls).toEqual([])
    vi.unstubAllGlobals()
    f = setup({ permission: 'default' })
    await syncPush()
    expect(f.calls).toEqual([])
    expect(f.notification.requestPermission).not.toHaveBeenCalled()
  })

  it('ressincroniza a mesma inscrição sem a trocar', async () => {
    const same = fakeSub('https://fcm.googleapis.com/fcm/send/a', KEY)
    const f = setup({ permission: 'granted', current: same })
    await syncPush()
    expect(same.unsubscribe).not.toHaveBeenCalled()
    expect(f.subscribe).not.toHaveBeenCalled()
    expect(f.calls.find((c) => c.method === 'POST')?.body).toEqual({
      endpoint: same.endpoint,
      keys: { p256dh: 'BROWSER-P256DH', auth: 'BROWSER-AUTH' },
    })
  })

  it('desligar apaga no servidor e no navegador', async () => {
    const cur = fakeSub('https://fcm.googleapis.com/fcm/send/a', KEY)
    const f = setup({ permission: 'granted', current: cur })
    await disablePush()
    expect(f.calls.find((c) => c.method === 'DELETE')).toEqual({
      method: 'DELETE',
      path: '/api/push/subscribe',
      body: { endpoint: cur.endpoint },
    })
    expect(cur.unsubscribe).toHaveBeenCalledOnce()
    expect(f.store.get('talos.push')).toBe('off')
  })
})
