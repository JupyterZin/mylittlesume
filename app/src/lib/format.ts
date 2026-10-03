// Datas e rótulos em pt-BR, no fuso do servidor (Europe/Lisbon por padrão).
import type { TaskStatus } from '../types'

let TZ = 'Europe/Lisbon'

export function setTimeZone(tz: string): void {
  try {
    new Intl.DateTimeFormat('pt-BR', { timeZone: tz })
    TZ = tz
  } catch {
    /* fuso inválido: mantém o anterior */
  }
}

/** O SQLite devolve datas sem fuso; no core elas são sempre UTC. */
export function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const s = /([zZ]|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? null : d
}

function fmt(d: Date, opts: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat('pt-BR', { timeZone: TZ, ...opts }).format(d)
}

/** 'AAAA-MM-DD' no fuso configurado. */
export function dayKey(d: Date): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(d)
  return parts
}

function dayDiff(a: Date, b: Date): number {
  const ka = Date.parse(`${dayKey(a)}T00:00:00Z`)
  const kb = Date.parse(`${dayKey(b)}T00:00:00Z`)
  return Math.round((ka - kb) / 86_400_000)
}

export function fmtTime(iso: string | null | undefined): string {
  const d = parseDate(iso)
  return d ? fmt(d, { hour: '2-digit', minute: '2-digit' }) : ''
}

/** "Hoje", "Ontem", "Amanhã" ou "seg., 5 de out." (com o ano se for outro). */
export function fmtDay(iso: string | null | undefined, now: Date = new Date()): string {
  const d = parseDate(iso)
  if (!d) return ''
  const diff = dayDiff(d, now)
  if (diff === 0) return 'Hoje'
  if (diff === -1) return 'Ontem'
  if (diff === 1) return 'Amanhã'
  const sameYear = fmt(d, { year: 'numeric' }) === fmt(now, { year: 'numeric' })
  return fmt(d, { weekday: 'short', day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }) })
}

/** "hoje às 14:05", "amanhã às 08:30", "qui., 8 de out. às 09:00". */
export function fmtWhen(iso: string | null | undefined, now: Date = new Date()): string {
  const d = parseDate(iso)
  if (!d) return '—'
  const day = fmtDay(iso, now)
  const time = fmtTime(iso)
  const lead = ['Hoje', 'Ontem', 'Amanhã'].includes(day) ? day.toLowerCase() : day
  return `${lead} às ${time}`
}

/** "agora", "há 5 min", "há 2 h", "há 3 dias", "em 20 min", "em 2 dias". */
export function fmtRelative(iso: string | null | undefined, now: Date = new Date()): string {
  const d = parseDate(iso)
  if (!d) return ''
  const sec = Math.round((d.getTime() - now.getTime()) / 1000)
  const abs = Math.abs(sec)
  const pre = sec < 0 ? 'há ' : 'em '
  if (abs < 45) return 'agora'
  if (abs < 3600) return `${pre}${Math.round(abs / 60)} min`
  if (abs < 86_400) return `${pre}${Math.round(abs / 3600)} h`
  const days = Math.round(abs / 86_400)
  return `${pre}${days} ${days === 1 ? 'dia' : 'dias'}`
}

const WEEKDAYS: Record<string, string> = {
  MO: 'segunda',
  TU: 'terça',
  WE: 'quarta',
  TH: 'quinta',
  FR: 'sexta',
  SA: 'sábado',
  SU: 'domingo',
}

/** Recorrências (RFC 5545) em linguagem de gente. */
export function humanizeRRule(rrule: string): string {
  const parts = Object.fromEntries(
    rrule
      .replace(/^RRULE:/i, '')
      .split(';')
      .map((p) => p.split('=') as [string, string])
      .filter(([k, v]) => k && v),
  ) as Record<string, string>
  const hour = parts.BYHOUR?.split(',')[0]
  const minute = parts.BYMINUTE?.split(',')[0] ?? '0'
  const at = hour !== undefined ? ` às ${hour.padStart(2, '0')}:${minute.padStart(2, '0')}` : ''
  const interval = Number(parts.INTERVAL ?? '1')
  const days = (parts.BYDAY ?? '').split(',').filter(Boolean)
  switch (parts.FREQ) {
    case 'DAILY':
      return interval > 1 ? `A cada ${interval} dias${at}` : `Todos os dias${at}`
    case 'WEEKLY': {
      const weekdays = ['MO', 'TU', 'WE', 'TH', 'FR']
      if (days.length === 5 && weekdays.every((d) => days.includes(d))) return `Dias úteis${at}`
      if (days.length === 1) {
        const name = WEEKDAYS[days[0]] ?? days[0]
        const fem = !['SA', 'SU'].includes(days[0])
        const every = interval > 1 ? `A cada ${interval} semanas, ${fem ? 'na' : 'no'} ${name}` : `${fem ? 'Toda' : 'Todo'} ${name}`
        return `${every}${at}`
      }
      if (days.length > 1) return `Toda semana (${days.map((d) => WEEKDAYS[d] ?? d).join(', ')})${at}`
      return interval > 1 ? `A cada ${interval} semanas${at}` : `Toda semana${at}`
    }
    case 'MONTHLY':
      return parts.BYMONTHDAY ? `Todo mês no dia ${parts.BYMONTHDAY}${at}` : `Todo mês${at}`
    case 'YEARLY':
      return `Todo ano${at}`
    case 'HOURLY':
      return interval > 1 ? `A cada ${interval} horas` : 'De hora em hora'
    default:
      return rrule
  }
}

export const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  planning: 'planejando',
  running: 'em andamento',
  waiting_approval: 'aguardando você',
  waiting_external: 'aguardando terceiros',
  scheduled: 'agendada',
  done: 'concluída',
  failed: 'falhou',
  cancelled: 'cancelada',
}

export type TaskGroup = 'andamento' | 'terceiros' | 'voce' | 'concluidas'

export const TASK_GROUPS: { id: TaskGroup; title: string }[] = [
  { id: 'voce', title: 'Aguardando você' },
  { id: 'andamento', title: 'Em andamento' },
  { id: 'terceiros', title: 'Aguardando terceiros' },
  { id: 'concluidas', title: 'Concluídas' },
]

export function taskGroup(status: TaskStatus): TaskGroup {
  switch (status) {
    case 'waiting_approval':
      return 'voce'
    case 'waiting_external':
      return 'terceiros'
    case 'done':
    case 'failed':
    case 'cancelled':
      return 'concluidas'
    default:
      return 'andamento'
  }
}

export const SCHEDULE_LABEL: Record<string, string> = {
  briefing: 'Briefing da manhã',
  reflection: 'Reflexão da noite',
  goal_checkin: 'Check-in de objetivo',
}

export function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`
}
