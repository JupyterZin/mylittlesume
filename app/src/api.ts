// Cliente HTTP do core: mesma origem; identidade pelo Tailscale + PIN opcional (X-Talos-Pin).
import { getPin } from './lib/storage'
import type {
  Agenda,
  AppState,
  Approval,
  MemoryFact,
  PushKey,
  SentinelRules,
  ServerMessage,
  SettingsView,
  Task,
  TaskEvent,
  Usage,
  VaultKey,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const pin = getPin()
  if (pin) headers['X-Talos-Pin'] = pin
  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'Sem conexão com o Talos.')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = (await res.json()) as { detail?: unknown }
      if (typeof j.detail === 'string') detail = j.detail
      else if (Array.isArray(j.detail)) detail = 'Dados inválidos.'
    } catch {
      /* corpo não-JSON */
    }
    throw new ApiError(res.status, detail || `Erro ${res.status}`)
  }
  return (await res.json()) as T
}

async function blob(path: string): Promise<Blob> {
  const headers: Record<string, string> = {}
  const pin = getPin()
  if (pin) headers['X-Talos-Pin'] = pin
  const res = await fetch(path, { headers, credentials: 'same-origin' })
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  return res.blob()
}

export const api = {
  state: () => req<AppState>('GET', '/api/state'),
  messages: (limit = 150) => req<ServerMessage[]>('GET', `/api/messages?limit=${limit}`),
  say: (text: string) => req<{ ok: boolean; answer: string | null }>('POST', '/api/messages', { text }),
  tasks: () => req<Task[]>('GET', '/api/tasks'),
  task: (id: number) => req<Task>('GET', `/api/tasks/${id}`),
  taskEvents: (id: number) => req<TaskEvent[]>('GET', `/api/tasks/${id}/events`),
  approvals: () => req<Approval[]>('GET', '/api/approvals'),
  approval: (id: number) => req<Approval>('GET', `/api/approvals/${id}`),
  screenshot: (id: number) => blob(`/api/approvals/${id}/screenshot`),
  decide: (id: number, decision: 'approve' | 'reject' | 'edit' | 'later', note = '') =>
    req<{ ok: boolean; message: string }>('POST', `/api/approvals/${id}/decide`, { decision, note }),
  pause: () => req<{ changed: boolean }>('POST', '/api/pause'),
  resume: () => req<{ changed: boolean }>('POST', '/api/resume'),
  takeover: (active: boolean) =>
    req<{ changed: boolean; takeover: AppState['takeover'] }>('POST', '/api/takeover', { active }),
  agenda: () => req<Agenda>('GET', '/api/agenda'),
  memory: (q = '') => req<MemoryFact[]>('GET', `/api/memory${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  memoryPut: (id: number, value: string) => req<MemoryFact>('PUT', `/api/memory/${id}`, { value }),
  memoryDelete: (id: number) => req<{ ok: boolean }>('DELETE', `/api/memory/${id}`),
  vaultKeys: () => req<VaultKey[]>('GET', '/api/vault/keys'),
  vaultPut: (key: string, value: string) =>
    req<{ ok: boolean; key: string }>('PUT', `/api/vault/${encodeURIComponent(key)}`, { value }),
  usage: () => req<Usage>('GET', '/api/usage'),
  rules: () => req<SentinelRules>('GET', '/api/sentinel/rules'),
  settings: () => req<SettingsView>('GET', '/api/settings'),
  pushKey: () => req<PushKey>('GET', '/api/push/key'),
  pushSubscribe: (body: { endpoint: string; keys: { p256dh: string; auth: string }; old_endpoint?: string | null }) =>
    req<{ ok: boolean; created: boolean; subscriptions: number }>('POST', '/api/push/subscribe', body),
  pushUnsubscribe: (endpoint: string) =>
    req<{ ok: boolean; removed: boolean; subscriptions: number }>('DELETE', '/api/push/subscribe', { endpoint }),
  pushTest: () => req<{ ok: boolean; sent: number; failed: number; removed: number }>('POST', '/api/push/test'),
}
