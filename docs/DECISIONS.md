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

## ADR-017 · Sistema 1 com Jev (TypeSafe) para poupar a assinatura
- **Contexto:** o Lucas está no plano Pro e pediu o Jev como "Sistema 1" para decisões pequenas. Isto altera a restrição 2.1 do SPEC ("inferência só pelo Agent SDK") por decisão explícita do dono: o Claude continua a ser o único que raciocina, escreve e usa ferramentas; o Jev só devolve julgamentos tipados (choice/noul/score com probabilidades).
- **Decisão:** cliente HTTP próprio (`talos/system1/client.py`, httpx) com o contrato do SDK oficial `typesafe-sdk` 0.7.2 (`POST /v1/systemone`, `Authorization: Bearer`, `{state, model: "jev-latest", questions}`), em vez de depender do SDK (que traz `httpx2` e outras dependências). A documentação viva (docs.typesafe.ai) e a API estão bloqueadas pela rede deste contêiner: o contrato foi lido do código do SDK e testado com servidor falso; validar no servidor com `talos doctor`.
- **Onde entra:** (1) roteamento da conversa principal — conversa leve vai para o Haiku, tarefas recebem dica para `task_create` (só com confiança ≥ 0,55); (2) triagem de respostas com resumo **extrativo** (o Jev escolhe as frases, o código copia-as); (3) deteção de injeção (regex **ou** Jev — só endurece); (4) classificador da Sentinela (Jev → Haiku de reserva; "ok" com confiança < 0,6 vira "ask"); (5) classificação de emails na organização semanal.
- **Privacidade:** tudo o que vai para o Jev passa por `sanitize()`: valores do cofre viram `[REDACTED:…]` e NIF/IBAN/cartão/telefone/código postal viram rótulos. O Jev é um terceiro; os emails (assunto, remetente, trechos) saem para ele — limitação registada em `SECURITY.md`.
- **Falhas:** Jev fora do ar nunca bloqueia nada: cada julgamento devolve `None` e quem chama cai no determinístico/Haiku. O uso fica em `usage_log` com `model="jev"` e não conta para o teto diário do Claude.

## ADR-018 · Plano Pro
- **Decisão:** `CLAUDE_PLAN=pro` → planejamento com Sonnet (Opus é escasso no Pro), teto diário padrão de 30 execuções, concorrência 1; `max5`/`max20` reativam o Opus e sobem o teto (60/150).

## ADR-019 · Organização semanal do Gmail (pedido do Lucas)
- **Decisão:** recorrência `gmail_organize` às segundas 09:00 (Lisboa) → job determinístico `gmail.organize`: lista `in:inbox -is:starred older_than:2d` (até 300), classifica com sinais do Gmail (`CATEGORY_*`, `List-Unsubscribe`) + Jev (categoria, precisa de resposta, importância), e propõe um `email.organize` (risco baixo): rótulos `Talos/<Categoria>` em tudo e **arquivo** só de promoções/newsletters/notificações sem resposta pendente e de baixa importância. Executor usa `batchModify`; nunca apaga; `/desfazer_organizacao` devolve os arquivados à caixa. Também disponível a pedido (`/organizar`, ferramenta `gmail_organize`).
- **Consequência:** zero uso da assinatura do Claude na organização (só Jev); sem Jev, só arquiva o que o próprio Gmail já classificou como promoções/atualizações/fóruns.

## ADR-020 · Navegador real (F4) — o que o Playwright MCP 0.0.83 faz de verdade ⚠️
- **Verificado contra o MCP e o Chromium reais:** as ações (navegar, clicar, escrever) **não** devolvem o snapshot inline: escrevem `<output-dir>/page-*.yml` e devolvem só um link. O `SnapshotIndex` lê esses ficheiros (apenas de `data_dir/screens`). Refs ganham prefixo `f<N>` depois de navegar (`f1e13`); linhas sem nome trazem o texto depois de `:` (`- generic [ref=f1e3] [cursor=pointer]: Finalizar compra`) — antes isso era ignorado e permitia disfarçar um clique final.
- **Teclas que submetem:** `Enter`, `NumpadEnter`, `Shift+Enter` e Espaço num botão submetem o formulário de teste → todas pedem aprovação. `browser_drop` = upload → `ask`. Ferramentas WebMCP registadas pela página → `deny`, e o MCP arranca com `--no-webmcp`. Aceitar diálogo (`browser_handle_dialog accept=true`) → `ask`.
- **Campos:** "Código postal"/"postal code" não são takeover (só egress); "chave de acesso" é takeover.
- **`vault_fill`:** o MCP não partilha refs com outra ligação, por isso `selector` aceita rótulo visível, placeholder ou CSS. Recusa campos de senha/cartão/código. O cartão leva screenshot e URL; se a aprovação chegar tarde e a página tiver mudado de site, o preenchimento é recusado.
- **Limitação confirmada (SPEC §7.4):** depois do `vault_fill` o snapshot seguinte mostra o valor ao modelo.

## ADR-021 · App PWA e mascote (F5)
- Vite + React 19 + TS + R3F + zustand + vite-plugin-pwa; fonte Archivo self-hosted; bundle principal ~91 KB gz, 3D carregado sob demanda (~265 KB gz). `RobotExpressive.glb` (CC0) versionado em `app/public/assets/talos.glb` (`infra/scripts/fetch_mascot.sh` verifica o SHA-256); recolor em runtime (bronze/pátina, ADR-014); 16 poses PNG geradas em headless servem de fallback 2D.
- **Estados do mascote** derivados no servidor (`channels/mascot.py`) e enviados no WS como `mascot_state`. `Sitting`/`Standing` no GLB são clipes únicos (sentar/levantar): tocam uma vez e seguram a pose. Aprovar → `Yes`; executado → `ThumbsUp`; recusar/expirar → `No`. "Resposta chegou" só no aviso real (não em auto-respostas). Aguardando aprovação vence horas de silêncio.
- **Rotas:** a página Tela vive em `/navegador` (o `tailscale serve` manda `/tela` para o noVNC); `/tela` no Telegram aponta para `/navegador`.
- **WebSocket com PIN:** navegadores não mandam cabeçalhos no WS → com `APP_PIN`, a primeira mensagem tem de ser `{"type":"auth","pin":…}` (senão fecha com 4401; 4403 para a allowlist Tailscale).
- **Cofre pelo app:** só escrita; chaves novas só `dados.*`; cada escrita gera evento `vault_updated` (só a chave). Memória editada no app fica com origem `dito`.

## ADR-022 · Notificações do próprio app (Web Push)
- **Decisão:** `pywebpush` com chave VAPID crua de 32 bytes criada no primeiro uso e guardada no cofre como segredo `webpush.vapid_private` (apagá-la revoga todos os aparelhos). Tabela `push_subscriptions` (migração `0002`), rotas `/api/push/{key,subscribe,test}`, service worker com `push-sw.js` importado. Só serviços de push conhecidos (FCM, Mozilla, WNS, Apple); no máximo 10 aparelhos.
- **Quando sai:** nos mesmos momentos que o Telegram (horas de silêncio incluídas). Cartões: urgência alta, TTL 12 h, tag `ap-<id>`, abrem `/aprovacoes/<id>`, **sem botão de aprovar** (o Lucas vê sempre o cartão completo). Respostas diretas só vão por push quando a conversa é do app e nenhuma janela do app está visível (o app reporta presença pelo WebSocket a cada 25 s).
- **Privacidade:** conteúdo cifrado ponta a ponta (o FCM vê só tamanho/hora), passado pelo redator e cortado (60/180 caracteres); cartões só com um resumo. Os resumos aparecem no ecrã de bloqueio.
- **`NOTIFY_CHANNELS`** (`telegram,app` por omissão): com `app`, o Telegram fica só como chat.
- **Corrida corrigida (pausa síncrona):** o gate regista quem espera pela decisão **antes** de enviar o cartão; uma aprovação muito rápida já não cai no caminho "pausa expirada" (que concederia e retomaria → ação em dobro).
- **WebSocket com sinal de vida** a cada 20 s; o app reconecta se ficar 45 s sem notícias e busca tudo ao voltar ao primeiro plano (o Android congela o PWA e deixa o socket morto).
