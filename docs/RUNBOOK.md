# Runbook do Talos

Tudo como administrador (com sudo), no servidor, via `ssh root@talos` pela tailnet (Termius no celular).
O checkout do Git fica em `/root/talos`; o `deploy` instala em `/opt/talos`. Os caminhos estão em [ARQUITETURA.md](ARQUITETURA.md) §3.

## Atualizar o servidor (depois de cada mudança no Git)
```bash
cd /root/talos && git pull && sudo make deploy && talos doctor
```
O `deploy` faz tudo isto:
- compila o app;
- sincroniza para `/opt/talos`;
- atualiza o venv;
- roda as migrações;
- instala as units do systemd e o atalho `talos`;
- reinicia os serviços.

Os jobs e o histórico sobrevivem. Se o app no celular não mostrar a novidade, feche e abra o app.

## Estado e logs
```bash
talos doctor                                  # saúde completa (Claude, Google, Telegram, Jev, navegador, Tela, monitor, backups)
systemctl status talos-core talos-browser talos-novnc
journalctl -u talos-core -f -o cat | jq -c .  # logs JSON (valores do cofre já vêm redigidos)
curl -s 127.0.0.1:8000/health | jq
```

## Reiniciar
```bash
sudo systemctl restart talos-core      # jobs e histórico sobrevivem (fila durável)
sudo systemctl restart talos-browser   # o perfil logado é persistente
```

## Botão de pânico
- Telegram: `/pausar` e `/retomar`. App: botão no topo. Servidor: `talos pause` / `talos resume`.
- Pausado: workers e executor param, execuções em curso são canceladas (voltam à fila), aprovações ficam congeladas. O estado sobrevive a reinícios.

## Rotacionar tokens
Use sempre `sudo talos secrets set CHAVE`. O valor não aparece na tela, os espaços colados são removidos e o formato é validado: `sk-ant-oat…` para o Claude, `apikey_…` para o Jev. O comando recusa `ANTHROPIC_*`.

**Claude (assinatura)**
1. Em qualquer computador com o Claude Code: `claude setup-token` → copie o token.
2. `sudo talos secrets set CLAUDE_CODE_OAUTH_TOKEN` → cole.
3. `sudo systemctl restart talos-core && talos doctor`.

**Google** (sintoma: alerta `invalid_grant` no Telegram)
1. `talos google-auth`
2. Abra o link, aceite, cole de volta a URL de `localhost` que o navegador não abriu.
3. `talos doctor`.

Se o token expira a cada 7 dias, a tela de consentimento está em "Testing": publique-a como "In production". A página inicial e a política de privacidade do branding estão no GitHub Pages, em `docs/index.html` e `docs/privacidade.html`.
Para trocar o cliente OAuth: `sudo talos secrets google-client` (cole o JSON ou o ID + segredo).

**Telegram**: @BotFather → `/revoke` → `sudo talos secrets set TELEGRAM_BOT_TOKEN` → reiniciar.

**Jev (TypeSafe)**: `sudo talos secrets set TYPESAFE_API_KEY` → reiniciar. Para desligar o Jev, ponha `SYSTEM1=off`: o Talos volta ao Haiku e passa a gastar mais da assinatura.

## Backups
- Automático: `talos-backup.timer` às 03:30 → `/var/lib/talos/backups/talos-AAAAMMDD-HHMM.tar.gz` (7 dias).
- Manual: `make backup`.
- A chave do cofre **não** vai no backup. Guarde uma cópia de `/etc/talos/vault.key` no seu gestor de senhas: sem ela, os dados do cofre no backup são ilegíveis (de propósito).
- Opcional: cópia semanal cifrada com `age` — crie `/etc/talos/backup.env` com `AGE_RECIPIENT=age1...`.

## Restaurar (e teste de restauração)
```bash
ls /var/lib/talos/backups/
cd /root/talos && make restore FILE=/var/lib/talos/backups/talos-AAAAMMDD-HHMM.tar.gz   # pede SIM; guarda o banco anterior
talos doctor
```
**Teste mensal**: restaurar o backup mais recente numa cópia (`TMP=$(mktemp -d); tar -C $TMP -xzf <arquivo>; sqlite3 $TMP/talos.db "PRAGMA integrity_check; SELECT count(*) FROM messages;"`) e conferir que o número de mensagens bate com o do dia.

## Atualizações de versões (mensal)
1. Para subir o Claude Code: suba `claude-agent-sdk` em `core/pyproject.toml` (o CLI vem embutido e fixado com o SDK) → `uv lock` → `make test` → commit.
2. No servidor, a atualização normal (acima) → mande "ping" no Telegram como teste de fumaça.
3. Se algo quebrar: `cd /root/talos && git checkout <commit anterior> && sudo make deploy`.

## Cofre
```bash
talos vault list                 # só os nomes (dados.nome_completo, dados.nif, …)
talos vault set dados.iban       # valor digitado duas vezes, sem eco
talos vault delete dados.iban    # pede confirmação
```

## Tela e teste do navegador
- A senha da Tela (VNC) foi mostrada **uma vez** no bootstrap. Em `/etc/talos/vnc.pass` ela fica codificada e não dá para ler. Para trocar:
  ```bash
  read -rsp "Nova senha da Tela: " P; echo; sudo x11vnc -storepasswd "$P" /etc/talos/vnc.pass >/dev/null; unset P
  sudo chown talos:talos /etc/talos/vnc.pass && sudo chmod 0600 /etc/talos/vnc.pass && sudo systemctl restart talos-novnc
  ```
- Abas abertas no Chromium: `curl -s 127.0.0.1:9222/json/list | jq '.[] | {type, url}'`.
- Formulário de teste (F4):
  ```bash
  cd /root/talos && (nohup bash infra/scripts/testpage.sh >/tmp/testpage.log 2>&1 &)
  ```
  Ele sobe em `http://127.0.0.1:9000/formulario.html`, que só o navegador do Talos vê.

## Revogar acessos
Ver `SECURITY.md` → "Como revogar acessos".

## Alertas que chegam no Telegram
| Alerta | O que fazer |
|---|---|
| Limite da assinatura atingido | Nada: o Talos retoma sozinho na hora indicada. |
| Monitor parado > 15 min | `journalctl -u talos-core -n 200`; `sudo systemctl restart talos-core`. |
| Renovação Google falhou | Rotacionar o token Google (acima). |
| Falhas repetidas de job | Ver `last_error` em `/health` e nos logs; `/tarefas` para ver o estado. |

## Problemas já vistos e a solução
São os casos reais do primeiro deploy. Todos já estão corrigidos no código; ficam aqui para referência.

| Sintoma | Causa | Solução |
|---|---|---|
| `secrets.env` dá erro numa linha / token inválido | Espaço colado junto do token, ou comentário na mesma linha de um valor (o systemd não aceita) | `sudo talos secrets set CHAVE`; comentários só em linhas próprias |
| `npm`/`npx` com `EACCES` ao correr como `talos` | Diretório atual em `/root` | Os scripts fazem `cd /` antes; faça o mesmo em comandos manuais |
| Chromium não arranca (sandbox) | AppArmor bloqueia user namespaces no Ubuntu 24.04 | Perfil `talos-chrome` instalado pelo `bootstrap.sh base` |
| Tela preta / noVNC sem ecrã | `PrivateTmp` escondia o socket do Xvfb | As units do navegador e do noVNC não usam `PrivateTmp` |
| Backup falha com `/tmp` só de leitura | `ProtectSystem=strict` sem `PrivateTmp` | `talos-backup.service` tem `PrivateTmp=yes`; o `deploy` reinstala as units |
| Google: "Access blocked" / branding incompleto | App em "Testing" sem página inicial nem política | Publicar "In production"; páginas no GitHub Pages |
| Monitor parado com 404 a cada ciclo | Rascunhos intermédios apagados no histórico do Gmail | Ignora `DRAFT`/mensagens apagadas; erro temporário não avança o `historyId` |
| `SSL: WRONG_VERSION_NUMBER` nos logs | `httplib2` partilhado entre threads | `GOOGLE_LOCK` serializa as chamadas ao Google |
| Resposta de email avisada, mas nada continua | Conversa sem tarefa: o evento morria | O evento sem tarefa volta à conversa principal (`agent.main_event`) |
| O app não mostra mensagens depois de ficar em segundo plano | WebSocket "zumbi" no Android | Sinal de vida a cada 20 s + recarregar ao voltar ao primeiro plano |
| A opção de notificações não aparece em Ajustes | Cache antiga do PWA | Fechar e abrir o app; se persistir: Chrome → ⋮ → Configurações do site → Limpar dados |
| "Agora submete" não faz nada | A conversa principal não tem navegador | `task_continue` encaminha o pedido à tarefa |
| Formulário aparece vazio | A página foi recarregada (perde os campos) | A persona proíbe recarregar páginas já preenchidas |
