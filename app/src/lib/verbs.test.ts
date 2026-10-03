import { describe, expect, it } from 'vitest'
import { APPROVE_VERB, approveVerb, doneLabel } from './verbs'

describe('verbo do botão de aprovação', () => {
  it('bate com a ação (SPEC §10)', () => {
    expect(approveVerb('email.send')).toBe('Aprovar e enviar')
    expect(approveVerb('email.reply')).toBe('Aprovar e enviar')
    expect(approveVerb('calendar.invite')).toBe('Aprovar e convidar')
    expect(approveVerb('browser.submit')).toBe('Aprovar e submeter')
    expect(approveVerb('purchase')).toBe('Aprovar e comprar')
    expect(approveVerb('booking')).toBe('Aprovar e reservar')
    expect(approveVerb('share_data')).toBe('Aprovar e partilhar')
    expect(approveVerb('delete')).toBe('Aprovar e apagar')
    expect(approveVerb('email.organize')).toBe('Aprovar e organizar')
  })

  it('tipo desconhecido cai num "Aprovar" neutro', () => {
    expect(approveVerb('algo.novo')).toBe('Aprovar')
  })

  it('cobre todos os tipos de ação do core', () => {
    const kinds = ['email.send', 'email.reply', 'calendar.invite', 'browser.submit', 'purchase', 'booking', 'share_data', 'delete']
    for (const k of kinds) expect(APPROVE_VERB[k]).toMatch(/^Aprovar e /)
  })

  it('histórico no passado', () => {
    expect(doneLabel('browser.submit', 'executed')).toBe('Aprovado e submetido')
    expect(doneLabel('email.send', 'executed')).toBe('Aprovado e enviado')
    expect(doneLabel('email.send', 'rejected')).toBe('Recusado')
    expect(doneLabel('email.send', 'superseded')).toBe('Substituído por uma versão editada')
  })
})
