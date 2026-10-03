// Verbo do botão de aprovação: tem de bater com a ação (SPEC §10, Anexo A). Espelha cards.py.

export const APPROVE_VERB: Record<string, string> = {
  'email.send': 'Aprovar e enviar',
  'email.reply': 'Aprovar e enviar',
  'calendar.invite': 'Aprovar e convidar',
  'browser.submit': 'Aprovar e submeter',
  purchase: 'Aprovar e comprar',
  booking: 'Aprovar e reservar',
  share_data: 'Aprovar e partilhar',
  delete: 'Aprovar e apagar',
  'email.organize': 'Aprovar e organizar',
}

export const ACTION_LABEL: Record<string, string> = {
  'email.send': 'Enviar email',
  'email.reply': 'Responder email',
  'calendar.invite': 'Enviar convite',
  'browser.submit': 'Submeter formulário',
  purchase: 'Concluir compra',
  booking: 'Fazer reserva',
  share_data: 'Partilhar dados pessoais',
  delete: 'Apagar',
  'email.organize': 'Organizar emails',
}

export function approveVerb(kind: string): string {
  return APPROVE_VERB[kind] ?? 'Aprovar'
}

export function actionLabel(kind: string): string {
  return ACTION_LABEL[kind] ?? kind
}

const DONE: Record<string, string> = {
  'email.send': 'Aprovado e enviado',
  'email.reply': 'Aprovado e enviado',
  'calendar.invite': 'Aprovado e convite enviado',
  'browser.submit': 'Aprovado e submetido',
  purchase: 'Aprovado e comprado',
  booking: 'Aprovado e reservado',
  share_data: 'Aprovado e partilhado',
  delete: 'Aprovado e apagado',
  'email.organize': 'Aprovado e organizado',
}

/** Resultado curto, já no passado, para o histórico ("Aprovado e enviado"). */
export function doneLabel(kind: string, status: string): string {
  switch (status) {
    case 'executed':
      return DONE[kind] ?? 'Aprovado e executado'
    case 'approved':
    case 'executing':
      return 'Aprovado · executando'
    case 'rejected':
      return 'Recusado'
    case 'superseded':
      return 'Substituído por uma versão editada'
    case 'expired':
      return 'Expirou sem resposta'
    case 'failed':
      return 'Falhou ao executar'
    default:
      return 'Aguardando você'
  }
}

export const RISK_LABEL: Record<string, string> = { baixo: 'baixo', medio: 'médio', alto: 'alto' }
