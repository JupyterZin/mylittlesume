// Estado do app (zustand): dados do core + tempo real do WebSocket + estado do mascote.
import { create } from 'zustand'
import { api, ApiError } from './api'
import { load, save } from './lib/storage'
import { dayKey } from './lib/format'
import type {
  AppState,
  Approval,
  ChatMessage,
  MascotPayload,
  MascotState,
  ServerMessage,
  Task,
  TaskEvent,
  WsEvent,
} from './types'

export type AuthState = 'loading' | 'ok' | 'pin' | 'forbidden' | 'offline'
export type ConnState = 'connecting' | 'open' | 'closed'

export interface Reaction {
  state: MascotState
  gesture: string | null
  status: string
  nonce: number
}

export interface Toast {
  id: number
  text: string
  tone: 'neutral' | 'bad'
}

interface Store {
  auth: AuthState
  conn: ConnState
  app: AppState | null
  messages: ChatMessage[]
  approvals: Approval[]
  tasks: Task[]
  mascot: MascotPayload
  reaction: Reaction | null
  typing: boolean
  timelines: Record<number, TaskEvent[]>
  toasts: Toast[]

  boot: () => Promise<void>
  refreshAll: () => Promise<void>
  refreshState: () => Promise<void>
  refreshMessages: () => Promise<void>
  refreshApprovals: () => Promise<void>
  refreshTasks: () => Promise<void>
  loadTimeline: (taskId: number) => Promise<void>
  send: (text: string) => Promise<void>
  retry: (key: string) => Promise<void>
  decide: (id: number, decision: 'approve' | 'reject' | 'edit' | 'later', note?: string) => Promise<boolean>
  setPaused: (paused: boolean) => Promise<void>
  setTyping: (typing: boolean) => void
  react: (state: MascotState, status: string, gesture?: string | null) => void
  clearReaction: (nonce: number) => void
  toast: (text: string, tone?: Toast['tone']) => void
  dismissToast: (id: number) => void
  setConn: (conn: ConnState) => void
  setAuth: (auth: AuthState) => void
  handle: (ev: WsEvent) => void
}

const IDLE: MascotPayload = {
  state: 'idle',
  once: false,
  base: 'idle',
  gesture: null,
  status: 'Pronto quando você quiser.',
  task_id: null,
  at: new Date(0).toISOString(),
}

let seq = 0
const nextKey = (p: string) => `${p}${Date.now().toString(36)}${(seq++).toString(36)}`

function fromServer(m: ServerMessage): ChatMessage {
  const meta = m.meta_json ?? {}
  return {
    key: `m${m.id}`,
    id: m.id,
    role: m.role,
    content: m.content,
    created_at: m.created_at,
    channel: m.channel,
    task_id: typeof meta.task_id === 'number' ? meta.task_id : null,
  }
}

function handleAuthError(e: unknown, set: (p: Partial<Store>) => void): boolean {
  if (e instanceof ApiError) {
    if (e.status === 401) {
      set({ auth: 'pin' })
      return true
    }
    if (e.status === 403) {
      set({ auth: 'forbidden' })
      return true
    }
  }
  return false
}

// pequenas esperas para juntar rajadas de eventos num só pedido
const timers: Record<string, ReturnType<typeof setTimeout>> = {}
function debounce(key: string, fn: () => void, ms = 180): void {
  clearTimeout(timers[key])
  timers[key] = setTimeout(fn, ms)
}

let speakHook: ((text: string) => void) | null = null
export function onAssistantMessage(fn: (text: string) => void): void {
  speakHook = fn
}

function greetingText(now = new Date()): string {
  const h = now.getHours()
  const part = h >= 5 && h < 12 ? 'Bom dia' : h >= 12 && h < 19 ? 'Boa tarde' : 'Boa noite'
  return `${part}, Lucas!`
}

export const useStore = create<Store>((set, get) => ({
  auth: 'loading',
  conn: 'connecting',
  app: null,
  messages: [],
  approvals: [],
  tasks: [],
  mascot: IDLE,
  reaction: null,
  typing: false,
  timelines: {},
  toasts: [],

  boot: async () => {
    try {
      const app = await api.state()
      set({ app, auth: 'ok', mascot: app.mascot })
    } catch (e) {
      if (!handleAuthError(e, set)) set({ auth: 'offline' })
      return
    }
    await get().refreshAll()
    // saudação: ao abrir o app pela primeira vez no dia (SPEC §9.3)
    const today = dayKey(new Date())
    if (load('talos.greeted') !== today) {
      save('talos.greeted', today)
      get().react('greeting', greetingText())
    }
  },

  refreshAll: async () => {
    await Promise.all([get().refreshState(), get().refreshMessages(), get().refreshApprovals(), get().refreshTasks()])
  },

  refreshState: async () => {
    try {
      const app = await api.state()
      set({ app, auth: 'ok', mascot: app.mascot })
    } catch (e) {
      handleAuthError(e, set)
    }
  },

  refreshMessages: async () => {
    try {
      const rows = await api.messages()
      const server = rows.map(fromServer)
      // mantém as mensagens locais que o servidor ainda não confirmou
      const local = get().messages.filter((m) => m.local && (m.pending || m.failed))
      set({ messages: [...server, ...local] })
    } catch (e) {
      handleAuthError(e, set)
    }
  },

  refreshApprovals: async () => {
    try {
      set({ approvals: await api.approvals() })
    } catch (e) {
      handleAuthError(e, set)
    }
  },

  refreshTasks: async () => {
    try {
      set({ tasks: await api.tasks() })
    } catch (e) {
      handleAuthError(e, set)
    }
  },

  loadTimeline: async (taskId) => {
    try {
      const events = await api.taskEvents(taskId)
      set({ timelines: { ...get().timelines, [taskId]: events } })
    } catch (e) {
      handleAuthError(e, set)
    }
  },

  send: async (text) => {
    const key = nextKey('l')
    const msg: ChatMessage = {
      key,
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
      channel: 'app',
      pending: true,
      local: true,
    }
    set({ messages: [...get().messages, msg], typing: false })
    try {
      const res = await api.say(text)
      set({
        messages: get().messages.map((m) => (m.key === key ? { ...m, pending: false } : m)),
      })
      if (res.answer) {
        set({
          messages: [
            ...get().messages,
            { key: nextKey('a'), role: 'assistant', content: res.answer, created_at: new Date().toISOString(), local: true },
          ],
        })
      }
    } catch (e) {
      if (handleAuthError(e, set)) return
      set({ messages: get().messages.map((m) => (m.key === key ? { ...m, pending: false, failed: true } : m)) })
    }
  },

  retry: async (key) => {
    const m = get().messages.find((x) => x.key === key)
    if (!m) return
    set({ messages: get().messages.filter((x) => x.key !== key) })
    await get().send(m.content)
  },

  decide: async (id, decision, note = '') => {
    try {
      const res = await api.decide(id, decision, note)
      get().toast(res.message, res.ok ? 'neutral' : 'bad')
      await get().refreshApprovals()
      return res.ok
    } catch (e) {
      if (!handleAuthError(e, set)) get().toast(e instanceof Error ? e.message : 'Não foi possível decidir.', 'bad')
      return false
    }
  },

  setPaused: async (paused) => {
    try {
      if (paused) await api.pause()
      else await api.resume()
      get().toast(paused ? 'Pausado. Nada roda até você retomar.' : 'De volta ao trabalho.')
      await get().refreshState()
    } catch (e) {
      if (!handleAuthError(e, set)) get().toast('Não consegui falar com o Talos.', 'bad')
    }
  },

  setTyping: (typing) => {
    if (get().typing !== typing) set({ typing })
  },

  react: (state, status, gesture = null) => {
    const cur = get().reaction
    if (cur && cur.state === state && cur.gesture === gesture) return
    set({ reaction: { state, status, gesture, nonce: ++seq } })
  },

  clearReaction: (nonce) => {
    if (get().reaction?.nonce === nonce) set({ reaction: null })
  },

  toast: (text, tone = 'neutral') => {
    const id = ++seq
    set({ toasts: [...get().toasts.slice(-2), { id, text, tone }] })
    setTimeout(() => get().dismissToast(id), 4200)
  },

  dismissToast: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),

  setConn: (conn) => set({ conn }),
  setAuth: (auth) => set({ auth }),

  handle: (ev) => {
    const s = get()
    switch (ev.type) {
      case 'mascot_state': {
        const p = ev.payload
        if (p.once) {
          s.react(p.state, p.status, p.gesture)
          set({ mascot: { ...p, state: p.base, once: false, status: p.base_status ?? s.mascot.status } })
        } else {
          set({ mascot: p })
        }
        return
      }
      case 'message': {
        const p = ev.payload
        if (p.role === 'user') {
          const pending = s.messages.find((m) => m.local && m.role === 'user' && m.content === p.content && !m.failed)
          if (pending) {
            set({ messages: s.messages.map((m) => (m.key === pending.key ? { ...m, pending: false } : m)) })
            return
          }
        }
        const msg: ChatMessage = {
          key: nextKey('w'),
          role: p.role,
          content: p.content,
          created_at: new Date().toISOString(),
          channel: p.channel,
          task_id: p.task_id ?? ev.task_id ?? null,
        }
        set({ messages: [...s.messages, msg] })
        if (p.role === 'assistant' && speakHook) speakHook(p.content)
        return
      }
      case 'approval_created':
      case 'approval_decided': {
        debounce('approvals', () => void get().refreshApprovals())
        debounce('tasks', () => void get().refreshTasks(), 400)
        debounce('state', () => void get().refreshState(), 300)
        appendTimeline(ev.task_id, ev.type, ev.payload, (ev as { id?: number }).id, (ev as { created_at?: string }).created_at)
        return
      }
      case 'task_event': {
        if (['task_created', 'task_status', 'task_done'].includes(ev.kind)) {
          debounce('tasks', () => void get().refreshTasks(), 250)
        }
        if (['paused', 'resumed', 'takeover_started', 'takeover_ended'].includes(ev.kind)) {
          debounce('state', () => void get().refreshState(), 100)
        }
        appendTimeline(ev.task_id, ev.kind, ev.payload, ev.id, ev.created_at)
        return
      }
    }
  },
}))

function appendTimeline(
  taskId: number | null,
  type: string,
  payload: Record<string, unknown>,
  id?: number,
  created_at?: string,
): void {
  if (taskId === null || id === undefined) return // só eventos gravados entram na auditoria
  const { timelines } = useStore.getState()
  const cur = timelines[taskId]
  if (!cur || cur.some((e) => e.id === id)) return
  const ev: TaskEvent = { id, task_id: taskId, type, payload_json: payload, created_at: created_at ?? new Date().toISOString() }
  useStore.setState({ timelines: { ...timelines, [taskId]: [...cur, ev] } })
}

export function pendingApprovals(approvals: Approval[]): Approval[] {
  return approvals.filter((a) => a.status === 'pending').sort((a, b) => a.id - b.id)
}
