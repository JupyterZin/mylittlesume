# Guia do Talos (para o Lucas)

O Talos é o seu agente pessoal. Ele conversa, cuida do seu Gmail, da sua agenda e do seu Drive, usa um navegador próprio e trabalha sozinho no que é seguro. **Tudo o que é sensível passa por você**: enviar um email, partilhar um dado pessoal, submeter um formulário, aceitar um convite, comprar ou reservar.

## 1. Onde falar com ele

| Canal | Como abrir | Para quê |
|---|---|---|
| **App Talos** (celular) | Ícone **Talos** na tela inicial, ou o endereço `https://talos.<sua-tailnet>.ts.net` no Chrome. Precisa do Tailscale ligado. | Conversa com o mascote, aprovações, tarefas, agenda, Tela e ajustes. |
| **Telegram** | O bot do Talos | Conversa rápida, cartões de aprovação e comandos. |

As duas conversas são independentes. Tarefas, aprovações e memória são as mesmas nos dois canais.

## 2. Como pedir as coisas

Fale normalmente, em português. Exemplos:

- "Que emails importantes chegaram hoje?"
- "Responde à Empresa X a dizer que aceito a reunião de quinta às 15h."
- "Pede orçamento a três empresas de mudanças em Lisboa."
- "Preenche o formulário em <link> com os meus dados e para antes de submeter."
- "Lembra-te que o meu contabilista é o João Silva."

O Talos decide sozinho o esforço:
- conversa leve vai para um modelo rápido;
- um pedido de vários passos vira uma **tarefa**, com plano curto e número (`#12`);
- um objetivo grande recebe um plano com marcos, que só começa depois do seu "sim".

Para continuar uma tarefa que está parada, diga pela conversa, por exemplo "agora submete" ou "continua a tarefa 12". O Talos encaminha o pedido à tarefa certa.

## 3. Aprovações (cartões)

Quando o Talos quer fazer algo sensível, chega um **cartão** com:
- o que ele vai fazer;
- o risco;
- os dados envolvidos;
- um print da página, quando é no navegador.

| Botão | O que faz |
|---|---|
| **Aprovar** (ex.: "Aprovar e enviar", "Aprovar e submeter") | Executa **uma vez**. Um toque duplo não duplica nada. |
| **Editar** | Você muda o texto e o Talos gera uma nova proposta. A antiga fica anulada. |
| **Recusar** | Não executa. O Talos é avisado e segue sem essa ação. |
| **Depois** | Fica pendente. Lembrete em 24 h; expira em 48 h. |

Os cartões chegam no Telegram e no app (aba **Aprovações**). Nos navegadores, a página fica **parada** à espera do seu toque, por até 15 minutos.

Destinatários aparecem marcados como "fornecido por você", "contato oficial", "participante da conversa" ou **"novo"**. Um destinatário novo é sempre risco alto: confira antes de aprovar.

## 4. O navegador do Talos e a Tela

- O Talos tem um Chromium próprio no servidor, sempre ligado. As sessões em que você fizer login lá ficam guardadas.
- A aba **Tela** do app (ou `/tela` no Telegram) mostra esse navegador ao vivo. Ela pede a **senha da Tela**.
- Fechar a Tela **não** interrompe o Talos. Ela serve só para você ver.
- **Senha, código 2FA e cartão o Talos nunca digita.** Quando chegar nessa parte, chega a mensagem 🖐️ **"Preciso que você assuma a Tela"**. Então:
  1. abra a Tela e toque em **Assumir controle** (o Talos pausa);
  2. digite você mesmo;
  3. toque em **Devolver ao Talos** (ele continua de onde parou).
- Seus dados pessoais (nome, NIF, morada, email, telefone) ficam no **cofre**. O Talos preenche com eles só depois de você aprovar o cartão "Aprovar e partilhar". Com uma aprovação ele preenche vários campos de uma vez.

## 5. O que ele faz sozinho

| Quando | O quê |
|---|---|
| A cada 3 min | Vigia o Gmail. Uma resposta numa conversa que ele acompanha gera um aviso 📬 com resumo, e a tarefa continua sozinha. |
| 3 dias úteis sem resposta | Propõe um **follow-up**, que você aprova. No máximo 2; depois sugere outro canal. |
| Email para `<seu-gmail>+talos@gmail.com` | Vira uma **tarefa**. Útil para encaminhar coisas ao Talos. |
| Todo dia às **08:30** | **Briefing** do dia: agenda, pendências, respostas. No máximo 8 linhas. |
| Todo dia às **23:00** | **Reflexão**: propõe o que aprendeu sobre você. A proposta aparece no briefing seguinte e só entra na memória depois do seu "sim". |
| Segunda às **09:00** | **Organização da caixa do Gmail**: manda um plano (rótulos `Talos/*` e arquivar). Só mexe depois de aprovar. `/desfazer_organizacao` reverte a última. |
| Emails suspeitos | Recebem o rótulo `Talos/Suspeito`, e você é avisado. Ele nunca segue instruções que vêm de emails ou páginas. |

**Horas de silêncio, 22:30–08:00:** avisos normais esperam até às 08:00. Só os urgentes passam.

## 6. Comandos do Telegram

| Comando | Para quê |
|---|---|
| `/tarefas` | Tarefas abertas e o estado de cada uma |
| `/aprovacoes` | Reenvia os cartões pendentes |
| `/agenda` | Vigilâncias (follow-ups) e rotinas agendadas |
| `/cancelar 12` | Cancela a tarefa #12, as vigilâncias dela e as propostas pendentes |
| `/organizar` | Organiza a caixa do Gmail agora (com aprovação) |
| `/desfazer_organizacao` | Desfaz a última organização |
| `/tela` | Link da Tela |
| `/uso` | Execuções de hoje (teto do plano Pro: 30 por dia) |
| `/pausar` · `/retomar` | **Botão de pânico**: para tudo na hora e retoma quando você quiser |

No app, o botão de pausa fica no topo e o uso aparece em **Ajustes**.

## 7. App: as 6 abas

- **Conversa**: chat com o mascote em 3D. O mascote mostra o estado do Talos: pensando, trabalhando, à espera de você, bloqueado, feliz. Há também ditado por voz.
- **Tarefas**: lista com o estado e o histórico de cada tarefa.
- **Aprovações**: cartões pendentes, com print e dados.
- **Agenda**: compromissos, follow-ups e rotinas.
- **Tela**: o navegador ao vivo, com **Assumir controle** e **Devolver**.
- **Ajustes**: "Notificações neste celular", uso do dia, pausa e PIN.

Se o app parecer desatualizado depois de uma atualização do servidor, feche e abra de novo. Se não resolver: Chrome → ⋮ → Configurações do site → Limpar dados → abrir de novo.

## 8. O cofre (seus dados pessoais)

- O cofre fica só no servidor, cifrado. O Talos vê apenas os **nomes** dos dados, por exemplo `dados.nif`, nunca os valores.
- Os valores só são usados:
  - no momento em que um email aprovado é enviado;
  - no momento em que um formulário aprovado é preenchido.
- Para acrescentar ou mudar um dado (no servidor, pelo Termius):
  ```
  talos vault set dados.iban
  ```
  O valor é digitado duas vezes e não aparece na tela. `talos vault list` mostra os nomes guardados.

## 9. O que o Talos nunca faz

- Enviar, partilhar, submeter, comprar, reservar ou aceitar convites sem a sua aprovação.
- Ver ou digitar senhas, códigos 2FA ou dados de cartão.
- Seguir instruções que vêm de emails, páginas ou anexos.
- Abrir portas na internet: só os seus aparelhos na tailnet chegam até ele.
- Usar uma chave de API paga. Ele roda **só pela sua assinatura Claude Pro**.

## 10. Se algo parecer errado

1. `/pausar` (ou o botão de pausa no app).
2. Me mande o print e a última mensagem do Talos.
3. Os passos técnicos estão no [RUNBOOK](RUNBOOK.md).
