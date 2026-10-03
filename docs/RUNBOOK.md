# Runbook do Talos

Tudo como administrador (com sudo), no servidor, via `ssh <usuario>@talos` (tailnet).

## Estado e logs
```bash
make doctor                                   # saúde completa (Claude, Google, Telegram, navegador, monitor, backups)
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
- Telegram: `/pausar` e `/retomar`. App: botão no topo. Servidor: `sudo -u talos /opt/talos/core/.venv/bin/talos pause` / `resume`.
- Pausado: workers e executor param, execuções em curso são canceladas (voltam à fila), aprovações ficam congeladas. O estado sobrevive a reinícios.

## Rotacionar tokens
**Claude (assinatura)**
1. No seu computador ou no servidor: `claude setup-token` → copie o token.
2. `sudo nano /etc/talos/secrets.env` → `CLAUDE_CODE_OAUTH_TOKEN=...`.
3. `sudo systemctl restart talos-core && make doctor`.

**Google** (sintoma: alerta `invalid_grant` no Telegram)
1. `sudo -u talos bash -c 'set -a; . /etc/talos/secrets.env; set +a; /opt/talos/core/.venv/bin/talos google-auth'`
2. Abra o link, aceite, cole de volta a URL de `localhost` que o navegador não abriu.
3. `make doctor`.
Se o token expira a cada 7 dias: a tela de consentimento está em "Testing" → publique como "In production".

**Telegram**: @BotFather → `/revoke` → novo token em `secrets.env` → reiniciar.

## Backups
- Automático: `talos-backup.timer` às 03:30 → `/var/lib/talos/backups/talos-AAAAMMDD-HHMM.tar.gz` (7 dias).
- Manual: `make backup`.
- A chave do cofre **não** vai no backup. Guarde uma cópia de `/etc/talos/vault.key` no seu gestor de senhas: sem ela, os dados do cofre no backup são ilegíveis (de propósito).
- Opcional: cópia semanal cifrada com `age` — crie `/etc/talos/backup.env` com `AGE_RECIPIENT=age1...`.

## Restaurar (e teste de restauração)
```bash
ls /var/lib/talos/backups/
make restore FILE=/var/lib/talos/backups/talos-AAAAMMDD-HHMM.tar.gz   # pede SIM; guarda o banco anterior
make doctor
```
**Teste mensal**: restaurar o backup mais recente numa cópia (`TMP=$(mktemp -d); tar -C $TMP -xzf <arquivo>; sqlite3 $TMP/talos.db "PRAGMA integrity_check; SELECT count(*) FROM messages;"`) e conferir que o número de mensagens bate com o do dia.

## Atualizações (mensal)
1. `git pull` no checkout do administrador.
2. Para subir o Claude Code: subir `claude-agent-sdk` em `core/pyproject.toml` (o CLI vem embutido e fixado com o SDK) → `uv lock` → commit.
3. `make deploy` → `make doctor` → mandar "ping" no Telegram (teste de fumaça).
4. Se algo quebrar: `git checkout <commit anterior> && make deploy`.

## Revogar acessos
Ver `SECURITY.md` → "Como revogar acessos".

## Alertas que chegam no Telegram
| Alerta | O que fazer |
|---|---|
| Limite da assinatura atingido | Nada: o Talos retoma sozinho na hora indicada. |
| Monitor parado > 15 min | `journalctl -u talos-core -n 200`; `sudo systemctl restart talos-core`. |
| Renovação Google falhou | Rotacionar o token Google (acima). |
| Falhas repetidas de job | Ver `last_error` em `/health` e nos logs; `/tarefas` para ver o estado. |
