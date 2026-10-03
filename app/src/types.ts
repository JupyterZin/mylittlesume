// Tipos da API do core (core/talos/channels/web_api.py).

export type MascotState =
  | 'idle'
  | 'greeting'
  | 'typing'
  | 'thinking'
  | 'working'
  | 'long_task'
  | 'waiting_approval'
  | 'approved'
  | 'rejected'
  | 'reply'
  | 'milestone'
  | 'error'
  | 'blocked'
  | 'quiet_hours'
  | 'paused'

export interface MascotPayload {
  state: MascotState
  once: boolean
  base: MascotState
  gesture: string | null
  status: string
  /** só nas reações: a linha de estado para quando a reação acabar */
  base_status?: string
  task_id: number | null
  at: string
}

export interface AppState {
  agent_name: string
  version: string
  user: string
  paused: boolean
  pause: { since: string | null; by: string | null } | null
  takeover: { active: boolean; since: string | null; by: string | null }
  rate_limited_until: string | null
  pending_approvals: number
  mascot: MascotPayload
  quiet_hours: { window: string; active: boolean; until: string }
  timezone: string
  auth_mode: string
  mascot_model: string
}

export type TaskStatus =
  | 'planning'
  | 'running'
  | 'waiting_approval'
  | 'waiting_external'
  | 'scheduled'
  | 'done'
  | 'failed'
  | 'cancelled'

export interface Task {
  id: number
  title: string
  goal: string
  status: TaskStatus
  priority: number
  summary: string
  due_at: string | null
  created_at: string
  updated_at: string
  parent_task_id: number | null
}

export interface TaskEvent {
  id?: number
  task_id: number | null
  type: string
  payload_json: Record<string, unknown>
  created_at: string
}

export interface Recipient {
  address: string
  status: string
  note: string
  source_url: string
}

export interface ApprovalDetails {
  action: string
  verb: string
  task_title: string
  to: Recipient[]
  subject: string
  when: string
  summary: string
  body: string
  personal_data: string[]
  raw_personal: string[]
  risk: string
  risk_level: string
  risk_why: string
  reason: string
  screenshot: boolean
}

export type ApprovalStatus =
  | 'pending'
  | 'approved'
  | 'executing'
  | 'rejected'
  | 'superseded'
  | 'expired'
  | 'executed'
  | 'failed'

export interface Approval {
  id: number
  task_id: number | null
  kind: string
  preview_text: string
  risk: string
  reason: string
  status: ApprovalStatus
  expires_at: string | null
  decided_at: string | null
  decided_via: string | null
  decision_note: string
  executed_at: string | null
  created_at: string
  card: string
  details: ApprovalDetails
}

export interface ChatMessage {
  key: string
  id?: number
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
  channel?: string
  task_id?: number | null
  pending?: boolean
  failed?: boolean
  local?: boolean
}

export interface ServerMessage {
  id: number
  conversation_id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
  meta_json: Record<string, unknown>
  channel: string
}

export interface Agenda {
  watches: {
    id: number
    task_id: number | null
    task_title: string
    kind: string
    target: string
    next_check_at: string | null
    followups_sent: number
    max_followups: number
    created_at: string | null
  }[]
  schedules: {
    id: number
    task_id: number | null
    task_title: string
    kind: string
    rrule: string
    prompt: string
    next_run_at: string | null
  }[]
  goals: {
    id: number
    title: string
    why: string
    cadence: string
    status: string
    next_checkin_at: string | null
    milestones: unknown[]
  }[]
}

export interface MemoryFact {
  id: number
  scope: string
  key: string
  value: string
  source: string
  created_at: string
  updated_at: string
}

export interface VaultKey {
  key: string
  kind: 'dado_pessoal' | 'segredo' | string
  label: string
  updated_at: string | null
}

export interface UsageDay {
  date: string
  runs: number
  turns: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  errors: number
  rate_limited: number
}

export interface Usage {
  auth_mode: string
  daily_limit: number
  today: UsageDay
  days: UsageDay[]
  models_today: Record<string, number>
  rate_limited_until: string | null
}

export interface Connector {
  id: string
  name: string
  ok: boolean
  detail: string
}

export interface SettingsView {
  agent_name: string
  version: string
  timezone: string
  auth_mode: string
  quiet_hours: { window: string; active: boolean; until: string }
  classifier: boolean
  pin_required: boolean
  daily_run_soft_limit: number
  connectors: Connector[]
  persona: string
  approval_ttl_hours: number
}

export interface SentinelRules {
  yaml: string
  classifier: boolean
  path: string
}

// Eventos tipados do WebSocket /ws
export type WsEvent =
  | { type: 'message'; task_id: number | null; payload: { role: ChatMessage['role']; content: string; channel?: string; task_id?: number | null; mascot?: string | null } }
  | { type: 'approval_created'; task_id: number | null; payload: { action_id: number; kind: string; risk?: string } }
  | { type: 'approval_decided'; task_id: number | null; payload: { action_id: number; decision: string; via?: string } }
  | { type: 'task_event'; kind: string; task_id: number | null; payload: Record<string, unknown>; id?: number; created_at?: string }
  | { type: 'mascot_state'; payload: MascotPayload }
