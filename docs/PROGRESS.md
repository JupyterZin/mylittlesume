# Progresso

Legenda: ✅ feito e verificado · ⏳ aguarda o servidor/Lucas · ⬜ por fazer.
"[offline]" = verificado aqui com `make test` (fakes, sem consumir a assinatura).

## Sessão 1 — 2026-10-03 (contêiner na nuvem, ver ADR-001)

### F0 · Fundação
- ✅ Esqueleto do repositório, `pyproject` com versões fixadas (`uv.lock`), `.env.example`, `Makefile`.
- ✅ `config.py`: aborta com `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` em `AUTH_MODE=subscription` [offline].
- ✅ `talos doctor` (autenticação, permissões, cofre, disco, banco, monitor, backups, pausa, Claude CLI, Telegram, Google, navegador, noVNC).
- ✅ `bootstrap.sh` por estágios (`base`, `tailscale`, `serve`, `firewall` com confirmação), `deploy.sh`, `backup.sh`, `restore.sh`, `browser.sh`; units systemd + timer de backup; `tailscale serve`.
- ✅ pre-commit com gitleaks; histórico verificado com gitleaks 8.28 (sem fugas).
- ⏳ [servidor] `talos doctor` verde; `claude -p "responda só OK"` como `talos`; `ss -tlnp` + scan externo.

### F1 · Núcleo conversacional
- ✅ Modelos de todas as tabelas + migração Alembic inicial; fila durável com lease e lock por tarefa.
- ✅ `AgentRuntime` (Agent SDK, `ClaudeSDKClient`) + `FakeRuntime`; perfis haiku/sonnet/opus.
- ✅ Conversa principal com `resume` e rotação diária com contexto determinístico.
- ✅ Telegram (long polling, allowlist, comandos), `workspace/CLAUDE.md`, memória, pausa persistente.
- ✅ [offline] "olá" → resposta; reinício não perde histórico nem jobs; outro `chat_id` ignorado e registado; `/pausar` bloqueia e `/retomar` volta.
- ⏳ [servidor] "olá" no Telegram responde em < 15 s.

### F2 · Google + Sentinela + aprovações + executor + cofre
- ✅ Cofre Fernet, `talos vault set` sem eco, placeholders, redação nos logs.
- ✅ Sentinela: allowlist, `rules.yaml`, egress, texto real do elemento via snapshot, classificador que só endurece, `sentinel_decision`.
- ✅ Aprovações (aprovar/editar/recusar/depois/expirar/lembrete/superseded) + pausa síncrona do navegador + concessão única.
- ✅ Executor idempotente (email, convite de calendário) + recuperação de `executing`.
- ✅ Conectores Gmail/Calendar/Drive (API oficial) + fakes; OAuth sem navegador (`talos google-auth`).
- ✅ Ferramentas MCP `mcp__talos__*` (23 na conversa principal, 24 nas tarefas); 10 skills (W2–W11).
- ✅ [offline] caso âncora até "enviado" com FakeGmail; recusar não envia; editar → `superseded`; toque duplo não duplica; placeholders só no envio; cofre fora dos logs; suíte de injeção (4 casos + takeover + pausa síncrona).
- ⏳ [servidor] caso âncora real para `<gmail>+empresa-teste@gmail.com` aprovado pelo Telegram.

### F3 · Monitor + follow-ups + inbox do agente + briefing
- ✅ `monitor/gmail_watch.py`: History API, ressincronização, triagem determinística + Haiku, follow-ups em dias úteis PT, inbox `+talos`, briefing 08:30 / reflexão 23:00, alertas (monitor parado, `invalid_grant`).
- ✅ [offline] resposta na thread → notificação com resumo + tarefa retomada; auto-resposta silenciosa e sem LLM; suspeito rotulado; 2 follow-ups e depois canal alternativo; `historyId` expirado recupera a resposta; email para `+talos` vira tarefa; briefing ≤ 8 linhas.
- ⏳ [servidor] resposta manual do Lucas na thread de teste → notificação em ≤ 5 min; briefing às 08:30.

### Verificação real do Agent SDK (sem chamar o modelo)
- ✅ `tests/smoke_handshake.py`: o CLI arranca com as opções reais; servidor MCP `talos` conectado (23 ferramentas na conversa, 24 nas tarefas); hooks aplicados; modo de permissão `default`.

## Sessão 1 (cont.) — respostas do Lucas
- Plano **Pro** → `CLAUDE_PLAN=pro`: planejamento com Sonnet, teto de 30 execuções/dia (ADR-018).
- **Sistema 1 = Jev (TypeSafe)** (ADR-017): roteamento da conversa (conversa leve → Haiku), triagem de respostas com resumo extrativo, deteção de injeção, classificador da Sentinela, classificação de emails. Redação de dados pessoais antes de sair. ✅ [offline] contrato + 10 testes com servidor falso. ⏳ chamada real: `api.typesafe.ai` está bloqueado pela rede deste contêiner — validar com `talos doctor` no servidor.
- **Organização semanal do Gmail** às segundas 09:00 (ADR-019): ✅ [offline] plano → cartão "Aprovar e organizar" → rótulos `Talos/*` + arquivo → `/desfazer_organizacao`; sem Jev usa as categorias do Gmail.
- **Takeover** da Tela: assumir controle pausa o agente; devolver retoma as tarefas. ✅ [offline].
- Gmail pessoal + plus-addressing `+talos`; horários confirmados (silêncio 22:30–08:00, briefing 08:30, reflexão 23:00).
- Dados para o cofre no setup (fornecidos pelo Lucas, **não** versionados): `dados.nome_completo`, `dados.telefone`.
- ⏳ **Máquina do servidor**: o contêiner desta sessão é temporário (apagado quando a sessão fica inativa, sem entrada de rede) — não pode ser o servidor do Talos. Falta escolher: VPS ou computador do Lucas.

### F4 · Navegador real (agente em paralelo, ADR-020)
- ✅ `CDPBrowser` (Playwright Python via CDP), `vault_fill` por rótulo/placeholder/CSS, screenshot e URL no cartão, formulário de teste (`infra/testpages/`), regras ajustadas ao formato REAL do MCP 0.0.83.
- ✅ [offline, com Chromium + MCP reais] formulário até antes de submeter → cartão com screenshot → submissão só depois da aprovação; senha/cartão → takeover; cliques disfarçados apanhados pelo texto real.
- ⏳ [servidor] o mesmo na VPS + assumir/devolver a Tela pelo celular.

### F5 · App PWA + mascote (agente em paralelo, ADR-021)
- ✅ 6 páginas (Conversa, Tarefas, Aprovações, Agenda, Tela, Ajustes), mascote 3D RobotExpressive em bronze com os 15 estados, `prefers-reduced-motion`, fallback 2D, PIN, ditado por voz; API e WS tipado; 41 testes Python + 28 vitest; `npm run build` sem erros.
- ⏳ [servidor] instalar no celular via Tailscale HTTPS; aprovar pelo app; fluidez num celular real.
- ⬜ Renders das poses no Telegram (os PNGs já existem em `app/public/`).

### Instalação na VPS (Hostinger KVM 2, Ubuntu 24.04)
- ✅ `bootstrap.sh base` testado num contêiner Ubuntu 24.04 (usuário, diretórios, venv, cofre, migrações, doctor); corrigidos: comentários inline no `.env` (systemd), chave do cofre criada como root, `PrivateTmp` que escondia o Xvfb da Tela, AppArmor para o sandbox do Chromium, `cd /` (npx como `talos` falhava com EACCES em `/root`).
- ✅ **F0 no servidor (VPS Hostinger KVM 2, Ubuntu 24.04)**: `bootstrap base` ok; Tailscale (`talos` 100.91.139.79) com acesso SSH pela tailnet testado no celular (Termius); UFW `deny incoming` + só `tailscale0`; `talos doctor`: Claude Code v2.1.286 responde "OK" pela assinatura (credencial `none`, sem API key), navegador CDP, Tela noVNC e Jev ✅.
- ✅ **F1 no servidor**: bot do Telegram com allowlist do `chat_id`; "olá" respondido pela assinatura.
- ✅ **F5 (parcial) no servidor**: `tailscale serve` publica o app em HTTPS da tailnet; no celular (Android) o mascote 3D aparece e o Talos responde pelo app.
- ✅ **Google no servidor**: projeto "Talos" no Google Cloud (Gmail, Calendar, Drive), cliente OAuth Desktop, branding com página inicial e política de privacidade no GitHub Pages (`docs/index.html`, `docs/privacidade.html`), `talos google-auth` pelo celular. `talos doctor` todo ✅ (Claude, Telegram, Google, navegador, Tela, Jev, monitor).
- ✅ Cofre com 5 `dados.*` (via `talos vault set`), primeiro backup (`talos-backup.service`).
- ✅ **F2 no servidor — caso âncora real**: pedido no Telegram → plano → cartão de aprovação → "Aprovar e enviar" → email entregue em `+empresa-teste` (Lucas confirmou).
- ⏳ F3 no servidor: resposta manual na thread → notificação com resumo (em teste). Tela pelo app, instalação como PWA.

### Próximas
- ⬜ F6: objetivos, `config/mcp.yaml`. ⬜ F7: endurecimento.
