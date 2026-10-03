import { describe, expect, it } from 'vitest'
import { fmtDay, fmtRelative, fmtTime, humanizeRRule, parseDate, taskGroup } from './format'
import { parseRoute, hrefFor } from '../router'
import { backoffMs } from '../live'
import { describeEvent } from './events'

describe('datas', () => {
  it('datas sem fuso vindas do SQLite são UTC', () => {
    expect(parseDate('2026-10-07T11:00:00')?.toISOString()).toBe('2026-10-07T11:00:00.000Z')
    expect(parseDate('2026-10-07T11:00:00+00:00')?.toISOString()).toBe('2026-10-07T11:00:00.000Z')
    expect(parseDate(null)).toBeNull()
  })

  it('hora local de Lisboa', () => {
    expect(fmtTime('2026-10-07T11:05:00Z')).toBe('12:05') // horário de verão
    expect(fmtTime('2026-12-07T11:05:00Z')).toBe('11:05')
  })

  it('hoje, ontem, amanhã', () => {
    const now = new Date('2026-10-07T12:00:00Z')
    expect(fmtDay('2026-10-07T08:00:00Z', now)).toBe('Hoje')
    expect(fmtDay('2026-10-06T08:00:00Z', now)).toBe('Ontem')
    expect(fmtDay('2026-10-08T08:00:00Z', now)).toBe('Amanhã')
  })

  it('tempo relativo', () => {
    const now = new Date('2026-10-07T12:00:00Z')
    expect(fmtRelative('2026-10-07T11:55:00Z', now)).toBe('há 5 min')
    expect(fmtRelative('2026-10-07T14:00:00Z', now)).toBe('em 2 h')
    expect(fmtRelative('2026-10-04T12:00:00Z', now)).toBe('há 3 dias')
    expect(fmtRelative('2026-10-07T12:00:10Z', now)).toBe('agora')
  })
})

describe('recorrências em linguagem de gente', () => {
  it.each([
    ['FREQ=DAILY;BYHOUR=8;BYMINUTE=30', 'Todos os dias às 08:30'],
    ['FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=8;BYMINUTE=30', 'Dias úteis às 08:30'],
    ['FREQ=WEEKLY;BYDAY=MO;BYHOUR=9', 'Toda segunda às 09:00'],
    ['FREQ=WEEKLY;BYDAY=SU;BYHOUR=19;BYMINUTE=0', 'Todo domingo às 19:00'],
    ['FREQ=MONTHLY;BYMONTHDAY=1;BYHOUR=9', 'Todo mês no dia 1 às 09:00'],
    ['RRULE:FREQ=DAILY;INTERVAL=2', 'A cada 2 dias'],
  ])('%s', (rule, text) => {
    expect(humanizeRRule(rule)).toBe(text)
  })
})

describe('tarefas e rotas', () => {
  it('grupos da página Tarefas', () => {
    expect(taskGroup('running')).toBe('andamento')
    expect(taskGroup('planning')).toBe('andamento')
    expect(taskGroup('waiting_external')).toBe('terceiros')
    expect(taskGroup('waiting_approval')).toBe('voce')
    expect(taskGroup('failed')).toBe('concluidas')
  })

  it('rotas (o /tela pertence ao noVNC)', () => {
    expect(parseRoute('/')).toEqual({ page: 'conversa' })
    expect(parseRoute('/aprovacoes/12')).toEqual({ page: 'aprovacoes', id: 12 })
    expect(parseRoute('/tarefas/3/')).toEqual({ page: 'tarefas', id: 3 })
    expect(parseRoute('/navegador')).toEqual({ page: 'tela' })
    expect(hrefFor({ page: 'tela' })).toBe('/navegador')
    expect(parseRoute('/qualquer')).toEqual({ page: 'conversa' })
  })

  it('timeline legível', () => {
    expect(describeEvent('approval_decided', { action_id: 4, decision: 'approved', via: 'app' })).toMatchObject({
      title: 'Proposta #4 aprovada',
      detail: 'pelo app',
      tone: 'good',
    })
    expect(describeEvent('sentinel_decision', { tool: 'Bash', decision: 'deny', reason: 'proibido' }).tone).toBe('bad')
  })
})

describe('reconexão', () => {
  it('backoff exponencial com teto de 30 s', () => {
    expect(backoffMs(0, () => 1)).toBe(500)
    expect(backoffMs(3, () => 1)).toBe(4000)
    expect(backoffMs(20, () => 1)).toBe(30000)
    expect(backoffMs(3, () => 0)).toBe(2400)
  })
})
