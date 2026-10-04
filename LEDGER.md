# LEDGER — memória de trabalho do desenvolvimento do Talos

> **Para quem constrói o Talos (Claude Code, ou outra pessoa).** Leia isto **antes de qualquer trabalho**. Atualize ao fim de cada bloco de trabalho e **antes de a conversa ficar longa**: o contexto pode ser compactado a qualquer momento, e o que não estiver aqui perde-se.
> Regras de escrita:
> - **Estado atual** e **Próximas ações** são reescritos;
> - **Diário** só cresce (append-only);
> - nunca há segredos nem dados pessoais (email, telefone, NIF…) neste ficheiro.

## 0. ⚠️ Trabalho a meio (2026-10-04) — ler primeiro

**Limpeza dos testes** (pedido do Lucas). O briefing de 04/10 chegou, mas ainda trata os testes como assunto real: a thread do gás natural e o email para a esposa ("Indo dormir").

**Onde os testes ficam no contexto:**
- tarefas (`task_list` lista todos os estados);
- vigilâncias ativas, que gerariam follow-ups;
- as últimas 12 mensagens da conversa, que entram na rotação diária;
- `memory_facts`, `contacts`, `workspace/memoria/`;
- a **memória automática do Claude Code** (`$HOME/.claude/projects/*/memory`, ativa por omissão no CLI 2.1.286). Desliga-se com `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`.

**Já escrito no working tree, NÃO commitado:**
- `core/talos/maintenance.py`: plano, cópia do banco, arquivar, cancelar, apagar fatos e contatos, mover ficheiros de memória para `data_dir/arquivo/`, `context_floor` em `system_state["context"]`;
- status `archived` em `TASK_STATUSES`;
- `tasks.list()` exclui `archived`;
- `_task_run` e `task_continue` ignoram `archived`;
- `_rotation_context` filtra pelo `context_floor`;
- o briefing não conta respostas de tarefas canceladas ou arquivadas;
- `sanitize_process_env` liga `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`.

**Falta:**
1. Imports:
   - `from talos.maintenance import context_floor` em `orchestrator/core.py`;
   - `Task` no import de `talos.db.models` em `monitor/gmail_watch.py`.

   A edição foi bloqueada pelo classificador de permissões; o Lucas tem de autorizar.
2. Comando CLI `talos limpar-testes [--antes] [--manter-fato ID] [--manter-contato ID] [--aplicar]`. Sem `--aplicar` só mostra o que faria.
3. Testes `core/tests/test_maintenance.py`.
4. RUNBOOK e ADR-023 (auto-memória desligada + limpeza).
5. Passos para o Lucas: `talos limpar-testes` → rever a lista → `--aplicar` → `sudo systemctl restart talos-core`.

**Paliativo sem código:** no Telegram, `/tarefas` e depois `/cancelar N` em cada tarefa de teste. Isso cancela as vigilâncias e as aprovações dessa tarefa.

## 1. Estado atual (atualizado em 2026-10-03)

- **Fases:**
  - F0–F5 construídas e **verificadas no servidor real**;
  - F6 e F7 por fazer;
  - plano de evolução v2 escrito em `docs/PLANO-V2.md` (só plano).
- **Branch de trabalho:** `claude/new-session-biws5d`. Faça push sempre para ele. **Não abrir PR** sem o Lucas pedir.
- **Último commit relevante:** documentação final + plano v2 (ver `git log`).
- **Testes:** 240 Python (`make test`) + 42 vitest (`make app-test`), todos verdes em 2026-10-03.
- **Em curso:** nada a meio. O PWA já está instalado no celular. O próximo passo é o Lucas confirmar o briefing das 08:30 e depois começar o v2 (F6a "Assuntos" é a recomendação).

## 2. Próximas ações (por ordem)

1. Perguntar ao Lucas: o briefing de 2026-10-04 às 08:30 chegou? (O PWA já está instalado ✅.)
2. Responder às 4 perguntas do `docs/PLANO-V2.md` §6. Cada uma tem um padrão, então dá para avançar sem a resposta.
3. **F6a · Assuntos** (`docs/PLANO-V2.md`, E1): ADR primeiro, depois o modelo de dados com migração, o roteador Jev, o ledger por assunto, o orçamento de sessão, a UI e o Telegram.
4. Depois: F6b fotos → F6c memória → F6d objetivos + MCP → F7 → F8 → F9.
5. Pendentes pequenos:
   - poses do mascote no Telegram (os PNGs estão em `app/public/poses/`);
   - `NOTIFY_CHANNELS=app`, se o Lucas quiser.

## 3. Como trabalhar com o Lucas

- Fala **português do Brasil**, com passos humanos **curtos, numerados e um de cada vez**, e esperar o "funcionou" antes do seguinte.
- Usa o **celular** (Android, Chrome; SSH pelo Termius). O Mac costuma estar desligado.
- **Pedir confirmação antes de:** firewall, SSH, rede, ou qualquer coisa que apague dados.
- **Nunca** pedir que cole segredos no chat. Tokens entram com `sudo talos secrets set CHAVE` e dados pessoais com `talos vault set dados.x`.
- Gosta de ambição ("nível world class, Muse da Meta"), mas valoriza que funcione primeiro.
- Atualizar o servidor (comando que ele já conhece):
  ```bash
  cd /root/talos && git pull && sudo make deploy
  ```

## 4. Ambiente e factos verificados

- **Servidor:**
  - VPS Hostinger KVM 2, Ubuntu 24.04;
  - host Tailscale `talos`;
  - sem portas públicas (UFW só na `tailscale0`);
  - app em `https://talos.<tailnet>.ts.net` (`tailscale serve`: `/` → `:8000`, `/tela` → `:6080`).
- **Caminhos:**
  - checkout `/root/talos`; instalação `/opt/talos`;
  - segredos `/etc/talos/secrets.env`; chave do cofre `/etc/talos/vault.key`;
  - dados `/var/lib/talos`; workspace do agente `/srv/talos/workspace`;
  - CLI `/usr/local/bin/talos` (wrapper).
- **Contas:**
  - Claude **Pro** pela assinatura (`CLAUDE_CODE_OAUTH_TOKEN`). **Nunca** `ANTHROPIC_API_KEY`;
  - Gmail pessoal com plus-addressing `+talos`;
  - Google OAuth "In production", com branding no GitHub Pages (`docs/index.html`, `docs/privacidade.html`);
  - Sistema 1 = Jev (TypeSafe).
- **Cofre** (só os nomes):
  - `dados.nome_completo`, `dados.nif`, `dados.morada`, `dados.email`, `dados.telefone`;
  - `google.token`, `webpush.vapid_*`.
- **Versões fixadas e o que se aprendeu delas:**
  - `claude-agent-sdk==0.2.163`, com o CLI 2.1.286 embutido:
    - usa `ClaudeSDKClient` (streaming);
    - **não** se põe nada em `allowed_tools`, porque isso anula o `can_use_tool`;
    - a Sentinela corre no hook `PreToolUse`; o "ask" é tratado em `can_use_tool` (pausa até 15 min);
    - o `query()` aceita `AsyncIterable[dict]`, o caminho para imagens se a ferramenta `Read` não servir.
  - **Playwright MCP 0.0.83** com `--cdp-endpoint http://127.0.0.1:9222 --output-dir … --image-responses omit --no-webmcp`:
    - as ferramentas usam `element` + `target` (refs `e12`/`f1e12`);
    - os snapshots vão para `page-*.yml`;
    - `NumpadEnter` e `Space` também submetem formulários.
  - `httplib2` não é thread-safe → `GOOGLE_LOCK` + `@serialized` nos conectores Google.
  - O systemd não aceita comentários na mesma linha de um valor no `.env`.
  - As units `talos-browser` e `talos-novnc` **não** podem usar `PrivateTmp` (socket do Xvfb). A `talos-backup` **precisa** de `PrivateTmp=yes`.
  - O Chromium no Ubuntu 24.04 precisa do perfil AppArmor `talos-chrome` (userns).
  - Rodar `npx` como `talos` exige `cd /` (EACCES em `/root`).
- **Desenho que importa lembrar:**
  - a conversa principal **não tem navegador**: cria tarefas (`task_create`) ou encaminha (`task_continue`);
  - os eventos sem tarefa voltam à principal (`agent.main_event`);
  - a aprovação regista `approvals.expect()` **antes** de enviar o cartão (corrida);
  - `vault_fill` aceita vários campos com uma aprovação e verifica que está no mesmo site aprovado;
  - o `deploy.sh` faz `rsync --delete` em `workspace/` (exceto `memoria/`). Tudo o que o agente aprender e guardar no workspace tem de ficar num diretório excluído.
- **Rede deste ambiente de desenvolvimento** (contêiner na nuvem): a pesquisa web funciona, mas o WebFetch é bloqueado para muitos domínios (about.fb.com, techcrunch, wikipedia, vellum…). Use resumos de pesquisa.

## 5. Mapa da documentação

| Ficheiro | Papel |
|---|---|
| `SPEC.md` | Especificação original (fonte dos requisitos) |
| `docs/PLAN.md` | Plano F0–F7 (histórico) |
| `docs/PLANO-V2.md` | **Plano v2** (pesquisa Muse, dots, Grok Bot + roteiro F6a–F9) |
| `docs/DECISIONS.md` | ADR-001…022 (a próxima é a ADR-023) |
| `docs/PROGRESS.md` | O que foi verificado, fase a fase |
| `docs/ARQUITETURA.md`, `docs/GUIA.md`, `docs/RUNBOOK.md`, `docs/SECURITY.md` | Técnico, uso, operação, segurança |
| `workspace/CLAUDE.md` | Persona do Talos em runtime (**não** é para o desenvolvimento) |

## 6. Diário (append-only)

### 2026-10-03 — sessão 1 (longa, compactada uma vez)
- O plano e as ADRs foram escritos, e F0–F5 construídas offline com fakes (240 testes).
- **Deploy na VPS com o Lucas, passo a passo:** bootstrap, Tailscale, UFW, tokens, Telegram, Google OAuth (publicado + páginas no GitHub Pages), cofre e backup.
- **Bugs reais encontrados e corrigidos no servidor:**
  - comentários inline no `.env`;
  - token colado com espaço;
  - `PrivateTmp` (Xvfb e backup);
  - AppArmor;
  - npx com EACCES;
  - 404 de rascunhos no histórico do Gmail;
  - SSL do `httplib2` entre threads;
  - eventos sem tarefa;
  - WebSocket zumbi no Android;
  - cache do PWA;
  - corrida na aprovação;
  - "agora submete" sem destino.
- **Verificado no real:**
  - email do caso âncora enviado depois da aprovação;
  - resposta → 📬 → continuação;
  - Web Push no celular;
  - F4 completo: preencher (`vault_fill` com 4 campos), submeter com aprovação, takeover de senha e cartão, assumir e devolver pelo celular.
- **Documentação final:** `README.md`, `GUIA.md`, `ARQUITETURA.md` e `RUNBOOK.md` com "problemas já vistos".
- **Pedido do Lucas no fecho:**
  - não misturar assuntos na mesma conversa e não estourar o contexto;
  - poder mandar fotos;
  - criar este ledger;
  - rever Muse, dots e Grok Bot. Resultado em `docs/PLANO-V2.md`, só plano.
- Depois do plano v2: o Lucas confirmou que **o app está instalado como PWA** no celular. F5 no servidor só fica à espera das poses do mascote no Telegram.
