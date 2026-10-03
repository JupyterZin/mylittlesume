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

### Próximas
- ⬜ F3: `monitor/gmail_watch.py` (History API), triagem Haiku, follow-ups, inbox `+talos`, briefing e reflexão.
- ⬜ F4: `vault_fill` real via CDP, screenshot para o cartão, página de formulário de teste, takeover/devolver.
- ⬜ F5: PWA + mascote. ⬜ F6: objetivos, `config/mcp.yaml`. ⬜ F7: endurecimento.
