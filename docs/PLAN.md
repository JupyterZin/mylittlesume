# Talos — Plano de construção

> Derivado do `SPEC.md` (v1.0). Decisões que tomei sozinho estão em `DECISIONS.md`; o andamento real fica em `PROGRESS.md`.

## 0. Onde estou construindo (importante)

O SPEC recomenda que eu rode **no próprio servidor**. Esta primeira sessão roda num **contêiner efêmero na nuvem** (Claude Code remoto), ligado ao repositório `jupyterzin/mylittlesume`. Consequências (ADR-001):

- Tudo o que é **código + testes com fakes** é feito e verificado aqui (sem consumir a assinatura).
- O que depende do servidor real (Tailscale, firewall, systemd, `claude setup-token`, BotFather, OAuth Google) fica pronto em scripts e passo a passo, e é validado **no servidor**, com o Lucas, uma etapa de cada vez.
- Por isso cada fase tem dois blocos de critérios: **[offline]** (verificado por `make test` aqui) e **[servidor]** (verificado no deploy).

## 1. Fases, entregáveis e dependências

```
F0 Fundação ──► F1 Núcleo ──► F2 Google+Sentinela+Aprovações ──► F3 Monitor/Follow-ups/Briefing
                                   │                                   │
                                   └──► F4 Navegador + Tela ◄──────────┘
                                              │
                                   F5 PWA + mascote (depende da API/WS da F1–F2)
                                   F6 Proatividade (depende de F3)
                                   F7 Endurecimento (depende de tudo)
```

### F0 · Fundação
Entregáveis: esqueleto do repo, `core/pyproject.toml` (uv, versões fixadas), `config.py` (pydantic-settings; aborta com `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` em `AUTH_MODE=subscription`), `talos doctor`, `infra/scripts/bootstrap.sh` idempotente (usuário `talos`, diretórios, Python/uv, Node, Claude CLI, Chromium, Xvfb/x11vnc/noVNC, Tailscale, UFW **com confirmação**), units systemd, `tailscale/serve.json`, `.env.example`, pre-commit com gitleaks, `Makefile`.
- [offline] testes de `config` (variáveis proibidas, `AUTH_MODE`), `doctor` com checks simulados, `bash -n` + shellcheck nos scripts.
- [servidor] `talos doctor` verde; `claude -p "responda só OK"` como `talos`; `ss -tlnp` + scan externo sem portas públicas.

### F1 · Núcleo conversacional
Entregáveis: modelos SQLite (todas as tabelas da seção 5) + Alembic; fila de jobs durável (lease + retry + `run_after`); `AgentRuntime` (Agent SDK, streaming) e `FakeRuntime`; roteamento de modelos (haiku/sonnet/opus); orquestrador com conversa principal (resume + rotação diária com resumo); bot Telegram (long polling, allowlist, comandos); `workspace/CLAUDE.md`; `memory_facts`; pausa persistente (`/pausar`, `/retomar`, `talos pause`).
- [offline] "olá" via `FakeTelegram` + `FakeRuntime` → resposta; reinício do processo não perde mensagens nem jobs (teste com o mesmo arquivo SQLite); chat_id estranho ignorado e registrado; pausa bloqueia o worker.
- [servidor] "olá" no Telegram responde em < 15 s.

### F2 · Google + Sentinela + aprovações + executor + cofre
Entregáveis: cofre Fernet + `talos vault set` sem eco + placeholders + filtro de redação no structlog; Sentinela (allowlist, `rules.yaml`, egress, classificador Haiku que só endurece, `sentinel_decision` em `task_events`); máquina de estados de `pending_actions` (aprovar/editar/recusar/expirar/lembrete/superseded, idempotência); executor (envio de rascunho com `Message-ID` determinístico, convite de calendário); conectores Gmail/Calendar/Drive + `FakeGmail`; servidor MCP in-process `talos` com as ferramentas da seção 6; cartões no Telegram; skills W2–W11; suíte de prompt injection.
- [offline] caso âncora com `FakeRuntime` roteirizado + `FakeGmail`: proposta → cartão → aprovar → enviado uma vez; recusar não envia; editar gera `superseded`; toque duplo não duplica; placeholders só resolvidos no executor; valores do cofre nunca nos logs; os 4 testes de injeção passam.
- [servidor] caso âncora real até `<gmail>+empresa-teste@gmail.com` aprovado pelo Telegram.

### F3 · Monitor + follow-ups + inbox do agente + briefing
Entregáveis: `gmail_watch` (History API a cada 3 min, ressincronização quando o `historyId` expira), triagem Haiku, follow-ups em dias úteis (calendário PT), inbox `+talos`, `Reply-To`, agendador (briefing 08:30, reflexão 23:00), horas de silêncio, alertas de saúde.
- [offline] diff de history com `FakeGmail`; auto-resposta = notificação silenciosa; follow-up com prazo encurtado; email para `+talos` vira tarefa; briefing ≤ 8 linhas.
- [servidor] resposta manual na thread de teste → notificação em ≤ 5 min.

### F4 · Navegador + Tela
Entregáveis: `talos-browser` (Xvfb + Chromium com perfil persistente, CDP só em 127.0.0.1), `talos-novnc`, Playwright MCP via CDP, pausa síncrona no `can_use_tool` com screenshot, `vault_fill`, takeover/devolver (pausa o agente), página de formulário local de teste.
- [offline] regras da Sentinela para cliques/campos (takeover em senha/cartão) com `FakeBrowser`.
- [servidor] formulário de teste até antes de submeter → cartão com screenshot → submissão só após aprovação; takeover pelo celular.

### F5 · App PWA + mascote + voz
Entregáveis: Vite + React + TS + R3F + zustand + vite-plugin-pwa; 6 páginas; WebSocket tipado; mascote RobotExpressive recolorido em bronze (override de material em runtime); tabela de estados 9.3; `prefers-reduced-motion`; fallback 2D (PNGs gerados em headless); renders para o Telegram; Web Speech API.
- [offline] build + testes de componentes + mapeamento estado→animação.
- [servidor] PWA instalável via `tailscale serve`; aprovar pelo app.

### F6 · Proatividade e extensões
Objetivos (Opus) + check-ins; reflexão noturna com diff de memória aplicado só após "sim"; `config/mcp.yaml` para servidores MCP extra; opcionais: Home Assistant (ações físicas = N2) e Oficina (Docker sem segredos).

### F7 · Endurecimento
Backup/restauração E2E, `RUNBOOK.md` e `SECURITY.md` completos, simulação de alertas.

## 2. Ordem de trabalho desta sessão

1. Docs de planejamento (este arquivo, `DECISIONS.md`, `PROGRESS.md`).
2. F0 (offline) → F1 (offline) → F2 (offline), com commits pequenos por bloco.
3. Parar e entregar ao Lucas as perguntas bloqueantes + o **primeiro** checkpoint humano.

## 3. Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| API do Agent SDK diferente do SPEC | Retrabalho no runtime | Pesquisa no código-fonte instalado + `DECISIONS.md`; `FakeRuntime` isola o resto do sistema |
| `can_use_tool` só funciona em modo streaming | Pausa síncrona não funciona com `query()` simples | Runtime usa `ClaudeSDKClient` (streaming) sempre |
| Ferramentas em `allowed_tools` pulam o `can_use_tool` | Sentinela "cega" para algumas chamadas | Sentinela aplicada no hook `PreToolUse` (roda para toda chamada); `can_use_tool` só trata o `ask` |
| Snapshot do Playwright expõe valor preenchido por `vault_fill` | Dado pessoal visível ao modelo | Documentado em `SECURITY.md`; egress continua bloqueando saída não aprovada |
| Refresh token Google expira em 7 dias (modo Testing) | Monitor para | Publicar como "In production"; alerta `invalid_grant` no Telegram |
| Limite da assinatura no meio de uma tarefa | Tarefa trava | Job `rate_limited` → pausa da fila → retoma automática + aviso único |
| Política de uso da assinatura mudar | Custo inesperado | `AUTH_MODE` alternável; `doctor` mostra o modo; uso frugal |
| Raspberry Pi com pouca RAM para Chromium + CLI | Lentidão/OOM | VPS como padrão; `MemoryMax` por serviço; concorrência 1 |
| Contêiner de build ≠ servidor | Bugs de ambiente só no deploy | `bootstrap.sh` idempotente + `doctor` + smoke test |

## 4. Perguntas bloqueantes para o Lucas

Todas têm um **padrão** que estou usando para não travar o código. Elas bloqueiam o **deploy**, não a escrita.

1. **Servidor:** já tem a VPS (Hostinger KVM 2, Ubuntu 24.04) ou vai ser o Raspberry Pi 4? *Padrão: VPS.*
2. **Assinatura Claude:** plano Pro ou Max (5x/20x)? Isso define o teto diário de execuções e quanto uso o Opus. *Padrão: Max 5x, teto 60/dia, Opus só em planejamento.*
3. **Gmail:** qual endereço o Talos vai usar? É conta `@gmail.com` pessoal ou Google Workspace? *Padrão: gmail pessoal + plus-addressing `+talos`.*
4. **Inbox do agente:** plus-addressing (`<gmail>+talos@gmail.com`) está bom, ou prefere uma conta Google só do Talos? *Padrão: plus-addressing.*
5. **Código no servidor:** o servidor clona este repositório do GitHub (é privado? então uso uma deploy key só-leitura) ou prefere que eu rode direto no servidor? *Padrão: clone com deploy key só-leitura.*
6. **Assinatura dos emails:** como quer assinar com as empresas (nome completo, ex.: "Lucas …")? Vai para o cofre como `dados.nome_completo`. *Padrão: placeholder `{{dados.nome_completo}}`.*
7. **Horários:** horas de silêncio 22:30–08:00, briefing 08:30 e reflexão 23:00 (Lisboa) estão ok? *Padrão: sim.*
