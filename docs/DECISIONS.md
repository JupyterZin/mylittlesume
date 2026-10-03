# Decisões (ADRs curtos)

Formato: **contexto → decisão → consequência**. Divergências entre o SPEC e a documentação/código atual estão marcadas com ⚠️.

## ADR-001 · Construção num contêiner na nuvem
- **Contexto:** o SPEC recomenda construir no servidor-alvo; esta sessão roda num contêiner efêmero do Claude Code remoto.
- **Decisão:** construir e testar tudo o que é código com fakes aqui; scripts de infraestrutura prontos e validados (`bash -n`/shellcheck); critérios "[servidor]" ficam para os checkpoints humanos.
- **Consequência:** fases marcadas como "offline ✅ / servidor ⏳" no `PROGRESS.md`.

## ADR-002 · Um processo asyncio + SQLite WAL com acesso síncrono
- **Contexto:** um único usuário, poucas escritas, concorrência de agentes 1–2.
- **Decisão:** SQLModel/SQLAlchemy síncrono sobre SQLite em WAL (`busy_timeout` 30 s); as chamadas são curtas e rodam no loop. Migrações Alembic aplicadas no arranque (`render_as_batch` para SQLite).
- **Consequência:** simples e robusto; se algum dia houver contenção, trocar por `aiosqlite` sem mudar os modelos.

## ADR-003 · Fila de jobs com lease e lock por tarefa
- **Contexto:** jobs têm de sobreviver a reinícios e nunca rodar duas vezes em paralelo para a mesma tarefa.
- **Decisão:** `jobs` ganha `locked_until`, `priority`, `max_attempts` e `dedupe_key`. `claim()` é um `UPDATE … WHERE id=(SELECT …) RETURNING id` atômico que ignora tarefas com job `running`. No arranque, todo `running` volta a `queued`. Limite da assinatura → `defer()` (volta à fila sem gastar tentativa) em vez de um estado `rate_limited` separado; o motivo fica em `last_error` e em `usage_log.rate_limited`.
- **Consequência:** sem perda de jobs; o estado "rate limited" é visível no log e no `/uso`.

## ADR-004 · Tabelas extra
- **Decisão:** `system_state` (chave → JSON: pausa, rate limit, último tick do monitor, `historyId`) e `inbound_rejected` (mensagens de chats fora da allowlist). `tasks` ganha `origin_conversation_id`, `model_profile` e `authorized_data_json` (chaves do cofre aprovadas pelo Lucas nesta tarefa). `pending_actions` ganha `executing` (estado intermédio para idempotência), `reminded_at`, `decision_note` e `card_refs_json`.

## ADR-005 · Agent SDK: versão, CLI e opções ⚠️
- **Contexto:** pesquisado no código instalado do `claude-agent-sdk` 0.2.163 e na documentação.
- **Decisões e divergências:**
  - O wheel traz um CLI embutido (2.1.286) e usa-o antes do PATH. **Padrão: CLI embutido** (fica fixado junto com o SDK; atualizar = subir a versão do SDK). `CLAUDE_CLI_PATH` permite usar o CLI do instalador nativo.
  - `can_use_tool` **já não exige** modo streaming; mesmo assim usamos `ClaudeSDKClient` para poder `interrupt()` (botão de pânico).
  - `system_prompt=None` manda prompt **vazio**: usamos `{"type": "preset", "preset": "claude_code", "append": …}`.
  - `setting_sources=["project"]` + `skills="all"` carregam `workspace/CLAUDE.md` e `workspace/.claude/skills` (há uma opção `skills` própria).
  - `tools=[…]` define os built-ins disponíveis (Bash nem entra no contexto) e `disallowed_tools` reforça.
  - `permission_mode="default"` explícito (se omitido, o CLI pode escolher `auto`).
  - **Nada** vai em `allowed_tools`: uma entrada lá pula o `can_use_tool` e cega a Sentinela.
  - Nomes das ferramentas MCP: `mcp__<chave do dict mcp_servers>__<ferramenta>`.
  - `resume=session_id` mantém o mesmo id; o id chega cedo em `SystemMessage(init).data["session_id"]`.
  - Rate limit chega como `RateLimitEvent(rate_limit_info.status == "rejected", resets_at)` ou `api_error_status == 429`; não há exceção própria.
  - O CLI dá prioridade a `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_API_KEY` sobre `CLAUDE_CODE_OAUTH_TOKEN`: o runtime remove-as do ambiente do filho e o `init.data["apiKeySource"]` é registrado para auditoria.

## ADR-006 · Sentinela: hook PreToolUse decide, `can_use_tool` executa o "ask"
- **Contexto:** hooks PreToolUse rodam para toda chamada (inclusive de subagentes) e têm precedência deny > ask > allow; um "ask" do hook cai no `can_use_tool`, que pode ficar pendente sem timeout do SDK.
- **Decisão:** o hook avalia (allowlist → `rules.yaml` → egress → classificador) e devolve `allow`/`deny`/`ask`. O `can_use_tool` reavalia (defesa em profundidade, com cache por `tool_use_id`) e, para `ask`, faz a **pausa síncrona** (cria `pending_action`, screenshot se for navegador, espera até 15 min). `takeover` = negar + pedir ao Lucas que assuma a Tela.
- **Consequência:** a Sentinela vê tudo; o classificador nunca afrouxa (falha do classificador = mantém a decisão).

## ADR-007 · Playwright MCP 0.0.83 ⚠️
- **Divergência:** as ferramentas de elemento usam `element` (descrição humana, opcional) + **`target`** (ref `e12` ou seletor), não `ref`. `browser_fill_form.fields[] = {name, type, target, value}`.
- **Decisão:** as regras avaliam `element`, `fields[].name` **e o texto real do elemento**, recuperado do último snapshot ARIA (`SnapshotIndex`, alimentado pelo hook PostToolUse) — assim o agente não consegue disfarçar um "Submeter" como "Ver mais". Ação de elemento sem descrição → `ask`. `browser_evaluate` e `browser_run_code_unsafe` → `deny`. `browser_type` com `submit=true`, `press_key Enter` e upload → `ask`. Conexão: `--cdp-endpoint http://127.0.0.1:9222` (reaproveita o contexto logado do perfil persistente).

## ADR-008 · Egress
- **Decisão:** valores literais do cofre (também URL-encoded e sem separadores) + padrões validados: NIF (dígito de controlo), IBAN (mod 97), cartão (Luhn), telefone PT/internacional, código postal PT (indicador de morada). Aplica-se a tudo o que sai do servidor (WebSearch, WebFetch, navegador, MCP extra); não se aplica às ferramentas internas `mcp__talos__*`. Uma chave do cofre aprovada numa tarefa (`authorized_data_json`) deixa de disparar o egress nessa tarefa.

## ADR-009 · Idempotência do envio de email
- **Decisão:** o executor gera um `Message-ID` determinístico a partir da `idempotency_key` (`<talos-<key>@talos.local>`) e, antes de enviar, procura `rfc822msgid:` na conta. Transição atômica `approved → executing` no banco. Toque duplo, retry e crash a meio ficam cobertos.

## ADR-010 · Rotação diária da conversa principal sem custo de LLM
- **Decisão:** a nova sessão do dia começa com um bloco de contexto **determinístico** (tarefas abertas, aprovações pendentes, últimas mensagens de ontem, truncadas), em vez de pedir um resumo ao modelo.
- **Consequência:** frugal; se ficar pobre, trocar por um resumo Haiku.

## ADR-011 · Agendamento
- **Decisão:** recorrências duráveis em `schedules` (RRULE interpretada em Europe/Lisbon, `python-dateutil`); o APScheduler só faz o "tique" periódico (monitor a cada 3 min, varredura de schedules/expirações a cada minuto). Dias úteis seguem o calendário de feriados de Portugal (`holidays`).

## ADR-012 · Telegram embutido no mesmo loop
- **Decisão:** `Application.initialize()` → `updater.start_polling()` → `start()` (sem `run_polling`, que toma conta do loop); encerramento na ordem `updater.stop()` → `stop()` → `shutdown()`. `callback_data` ≤ 64 bytes (`ap:<id>:<ação>`). Texto cortado em 4096 com "ver completo" no app.

## ADR-013 · OAuth Google sem navegador no servidor ⚠️
- **Divergência:** o fluxo OOB foi descontinuado.
- **Decisão:** `talos google-auth` usa `InstalledAppFlow` com `redirect_uri=http://localhost:8765/`, imprime a URL, e o Lucas cola de volta a URL (que "falha" no navegador) — trocamos `http://` por `https://` antes do `fetch_token`, mantendo a mesma instância do Flow (PKCE). O token vai para o cofre (`google.token`, segredo).

## ADR-014 · Mascote: recolor em runtime
- **Decisão:** override de material no carregamento (bronze `#B5762F` metálico no corpo, pátina `#4E8C80` nos detalhes), mantendo o `.glb` CC0 original intacto. Registrado agora; implementado na F5.

## ADR-015 · Conversa principal por canal, tarefas partilhadas
- **Decisão:** seguir o SPEC (uma conversa principal por canal), mas tarefas, aprovações e notificações são globais: o cartão de aprovação sai no Telegram **e** no app; a resposta final de uma tarefa vai para o canal de origem.

## ADR-016 · Monitor do Gmail
- **Decisão:** polling `users.history.list` (só `messageAdded`) a cada `MONITOR_INTERVAL_SECONDS`; ids já vistos guardados (últimos 500) para não processar duas vezes; `historyId` expirado (404) → ressincronização a partir do `last_marker` de cada vigilância. Ignorados: rascunhos, mensagens com `Message-ID` `<talos-…>`, o próprio email enviado (= `last_marker`) e mensagens só com `SENT`. Mensagens com `SENT`+`INBOX` contam (é o caso do teste E2E, em que o Lucas responde "como a empresa" para o próprio plus-address).
- **Triagem:** determinística primeiro (cabeçalho `Auto-Submitted`, assunto de auto-resposta, heurística de injeção) e só depois Haiku — auto-respostas não gastam LLM nem fazem som.
- **Follow-ups:** contam quando são **propostos** (no máximo 2); depois disso a tarefa é retomada para sugerir canal alternativo e a vigilância deixa de ter prazo (respostas continuam a ser detectadas).
- **Briefing/reflexão:** recorrências semeadas uma vez em `schedules`; o briefing recebe um bloco de dados determinístico e é cortado em 8 linhas; a reflexão não notifica (escreve o diff em `memoria/`).
