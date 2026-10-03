# Talos

Agente pessoal do Lucas, no estilo do Muse da Meta, com o **Claude como cérebro**. Ele usa o Claude Agent SDK oficial e roda pela **assinatura Claude Pro**, sem chave de API. Conversa pelo **Telegram** e por um **app no celular (PWA)** com um mascote 3D em bronze. Cuida do Gmail, da Agenda e do Drive, usa um navegador próprio que você pode ver e assumir (a "Tela") e trabalha sozinho no que é seguro. **Tudo o que é sensível espera a sua aprovação.**

## Estado (2026-10-03)

| Fase | O quê | Estado |
|---|---|---|
| F0 | Fundação: config, `doctor`, bootstrap, systemd, Tailscale, firewall | ✅ no servidor |
| F1 | Núcleo: conversa, fila durável, Telegram, pausa | ✅ no servidor |
| F2 | Google, Sentinela, aprovações, executor, cofre | ✅ no servidor (email real enviado após aprovação) |
| F3 | Monitor do Gmail, follow-ups, inbox `+talos`, briefing, reflexão, organização semanal | ✅ resposta → aviso → continuação; ⏳ confirmar briefing, follow-up e `+talos` no uso real |
| F4 | Navegador real + Tela + takeover | ✅ no servidor (preencher, submeter, assumir/devolver pelo celular) |
| F5 | App PWA + mascote + notificações do app | ✅ no celular; ⏳ instalar como app e mostrar as poses no Telegram |
| F6–F9 | **v2**: conversas por assunto, fotos e documentos, memória visível, objetivos, aprovações com escopo, voz, ensinar uma tarefa | 📝 planejado em [docs/PLANO-V2.md](docs/PLANO-V2.md) |
| F7 | Endurecimento: teste de restauração, simulação de alertas | ⬜ |

O detalhe de cada fase está em [docs/PROGRESS.md](docs/PROGRESS.md).

## Documentação

| Documento | Para quem | Conteúdo |
|---|---|---|
| [docs/GUIA.md](docs/GUIA.md) | Lucas | Como usar o Talos no dia a dia: pedidos, aprovações, Tela, comandos, rotinas |
| [docs/ARQUITETURA.md](docs/ARQUITETURA.md) | Técnico | Componentes, fluxos, perfis de modelo, ferramentas, dados, mapa do código |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Operação | Atualizar, logs, tokens, backups, restauração, problemas já vistos |
| [docs/SECURITY.md](docs/SECURITY.md) | Segurança | Modelo de ameaças, fronteiras de confiança, limites conhecidos, revogação |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Técnico | Decisões de arquitetura (ADR-001 a 022) |
| [docs/PLANO-V2.md](docs/PLANO-V2.md) | Todos | **Próximo passo**: pesquisa Muse / dots / Grok Bot e roteiro (assuntos separados, fotos, memória visível…) |
| [LEDGER.md](LEDGER.md) | Desenvolvimento | Memória de trabalho: estado, próximas ações, factos do servidor, diário |
| [docs/PLAN.md](docs/PLAN.md) | Histórico | Plano de construção por fases |
| [docs/PROGRESS.md](docs/PROGRESS.md) | Todos | O que foi feito e verificado, e o que falta |
| [SPEC.md](SPEC.md) | Referência | Especificação original |

## Regras que não mudam

- **Sem `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`** no ambiente: o arranque e o `talos doctor` abortam. Só a assinatura, via `claude setup-token`.
- **Nada sensível sem aprovação**: o modelo só propõe e quem executa é o executor determinístico, uma vez.
- **O agente nunca vê senhas, códigos 2FA nem dados de cartão.** Nesses casos, você assume a Tela.
- **Conteúdo externo é não confiável**: emails e páginas nunca dão ordens ao Talos.
- **Nenhuma porta pública**: só a tailnet (Tailscale) chega ao servidor.
- **Segredos nunca no Git**: só existe o `.env.example`, e há gitleaks no pre-commit.

## Atalhos

No servidor (VPS Hostinger KVM 2, Ubuntu 24.04, via Tailscale):

```bash
cd /root/talos && git pull && sudo make deploy   # atualizar
talos doctor                                     # saúde completa
journalctl -u talos-core -f -o cat               # logs
talos pause | talos resume                       # botão de pânico
```

Em desenvolvimento (não consome a assinatura):

```bash
make test        # 240 testes Python com fakes
make app-test    # 42 testes do app (vitest)
make lint
```

## Estrutura

```
core/       backend Python (orquestrador, runtime Agent SDK, Sentinela, conectores, canais)
app/        PWA (Vite + React + React Three Fiber)
workspace/  persona (CLAUDE.md) e skills do agente
infra/      bootstrap, deploy, backup/restauração, systemd, Tailscale, páginas de teste
docs/       documentação (+ páginas do GitHub Pages para o OAuth do Google)
```
