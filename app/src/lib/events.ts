// Eventos de auditoria (task_events) → frase curta em pt-BR para a timeline da tarefa.
import { actionLabel } from './verbs'
import { TASK_STATUS_LABEL } from './format'
import type { TaskStatus } from '../types'

export type Tone = 'neutral' | 'good' | 'warn' | 'bad' | 'agent'

export interface Described {
  title: string
  detail?: string
  tone: Tone
}

const DECISION: Record<string, string> = {
  allow: 'permitiu',
  ask: 'pediu aprovação',
  deny: 'bloqueou',
  takeover: 'pediu que você assuma',
}

const APPROVAL_DECISION: Record<string, [string, Tone]> = {
  approved: ['aprovada', 'good'],
  rejected: ['recusada', 'bad'],
  edit: ['devolvida para edição', 'neutral'],
  expired: ['expirou', 'warn'],
}

const TRIAGE: Record<string, string> = {
  resposta_util: 'resposta útil',
  auto_resposta: 'resposta automática',
  pede_dados: 'pede dados',
  suspeito: 'suspeito',
}

export function friendlyTool(tool: string): string {
  return tool
    .replace(/^mcp__playwright__browser_/, 'navegador · ')
    .replace(/^mcp__talos__/, '')
    .replace(/_/g, ' ')
}

function s(v: unknown): string {
  return v === undefined || v === null ? '' : String(v)
}

export function describeEvent(type: string, p: Record<string, unknown>): Described {
  switch (type) {
    case 'task_created':
      return { title: 'Tarefa criada', detail: s(p.title), tone: 'neutral' }
    case 'task_status': {
      const to = TASK_STATUS_LABEL[p.to as TaskStatus] ?? s(p.to)
      const from = TASK_STATUS_LABEL[p.from as TaskStatus] ?? s(p.from)
      const tone: Tone = p.to === 'done' ? 'good' : p.to === 'failed' ? 'bad' : 'neutral'
      return { title: `Agora: ${to}`, detail: from ? `antes: ${from}` : undefined, tone }
    }
    case 'task_done':
      return { title: 'Tarefa concluída', tone: 'good' }
    case 'run_started':
      return { title: 'O Talos começou a trabalhar', detail: s(p.model) || undefined, tone: 'agent' }
    case 'working':
      return { title: 'Trabalhando', tone: 'agent' }
    case 'tool_call':
      return { title: `Usou ${friendlyTool(s(p.tool))}`, tone: 'agent' }
    case 'sentinel_decision': {
      const d = s(p.decision)
      const tone: Tone = d === 'deny' || d === 'takeover' ? 'bad' : d === 'ask' ? 'warn' : 'neutral'
      return {
        title: `Sentinela ${DECISION[d] ?? d}: ${friendlyTool(s(p.tool))}`,
        detail: s(p.reason) || undefined,
        tone,
      }
    }
    case 'approval_created':
      return {
        title: `Proposta #${s(p.action_id)} criada`,
        detail: [actionLabel(s(p.kind)), p.risk ? `risco ${s(p.risk).replace('medio', 'médio')}` : '']
          .filter(Boolean)
          .join(' · '),
        tone: 'warn',
      }
    case 'approval_decided': {
      const [word, tone] = APPROVAL_DECISION[s(p.decision)] ?? [s(p.decision), 'neutral' as Tone]
      const via = p.via === 'app' ? 'pelo app' : p.via === 'telegram' ? 'pelo Telegram' : ''
      return { title: `Proposta #${s(p.action_id)} ${word}`, detail: via || undefined, tone }
    }
    case 'action_executed':
      return { title: `Proposta #${s(p.action_id)} executada`, detail: actionLabel(s(p.kind)), tone: 'good' }
    case 'action_failed':
      return { title: `Falhou ao executar #${s(p.action_id)}`, detail: s(p.error), tone: 'bad' }
    case 'reply_received':
      return { title: 'Chegou uma resposta', detail: [s(p.from), s(p.subject)].filter(Boolean).join(' · '), tone: 'good' }
    case 'triage':
      return { title: `Triagem: ${TRIAGE[s(p.classe)] ?? s(p.classe)}`, detail: s(p.resumo) || undefined, tone: 'neutral' }
    case 'followup_due':
      return { title: `Hora do follow-up ${s(p.n)}`, tone: 'warn' }
    case 'draft_created':
      return { title: 'Rascunho criado', detail: s(p.subject) || undefined, tone: 'neutral' }
    case 'note':
      return { title: 'Nota', detail: s(p.text), tone: 'neutral' }
    case 'takeover_requested':
      return { title: 'Pediu que você assuma a Tela', detail: s(p.reason) || undefined, tone: 'warn' }
    case 'takeover_started':
      return { title: 'Você assumiu a Tela', tone: 'neutral' }
    case 'takeover_ended':
      return { title: 'Você devolveu a Tela ao Talos', tone: 'neutral' }
    case 'paused':
      return { title: 'Pausado', detail: s(p.by) || undefined, tone: 'warn' }
    case 'resumed':
      return { title: 'Retomado', detail: s(p.by) || undefined, tone: 'neutral' }
    case 'suspicious_content':
      return { title: 'Conteúdo suspeito marcado', detail: s(p.from) || s(p.origin), tone: 'bad' }
    case 'job_failed':
      return { title: 'Uma execução falhou', detail: s(p.error), tone: 'bad' }
    case 'notification_deferred':
      return { title: 'Aviso adiado para depois das horas de silêncio', tone: 'neutral' }
    case 'vault_updated':
      return { title: `Cofre: ${s(p.key)} atualizado`, tone: 'neutral' }
    case 'message':
      return { title: 'Mensagem', detail: s(p.content).slice(0, 200), tone: 'neutral' }
    default:
      return { title: type.replace(/_/g, ' '), tone: 'neutral' }
  }
}
