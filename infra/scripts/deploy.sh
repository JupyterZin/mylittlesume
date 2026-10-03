#!/usr/bin/env bash
# Copia o repositório para /opt/talos, prepara o venv e o workspace do agente, aplica migrações.
# Uso: sudo infra/scripts/deploy.sh [--no-restart]
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Os comandos que rodam como `talos` herdam o diretório atual; /root é 0700 e o npm falha com EACCES.
cd /
RESTART=1
[[ "${1:-}" == "--no-restart" ]] && RESTART=0
[[ $EUID -eq 0 ]] || { echo "Rode com sudo."; exit 1; }
as_talos() { sudo -u talos -H env PATH=/usr/local/bin:/usr/bin:/bin "$@"; }

# App (PWA): compila antes de copiar, se existir
if [[ -f "$REPO_DIR/app/package.json" ]] && command -v npm >/dev/null; then
  (cd "$REPO_DIR/app" && npm ci --no-audit --no-fund && npm run build)
fi

# app PWA: gera app/dist antes de copiar (o core serve-o em /). Roda como o administrador que chamou
# o sudo, para não deixar node_modules de root no repositório.
if [[ -f "$REPO_DIR/app/package.json" ]]; then
  if command -v npm >/dev/null; then
    BUILD_USER="${SUDO_USER:-root}"
    sudo -u "$BUILD_USER" -H bash -c "cd '$REPO_DIR/app' && npm ci --no-audit --no-fund && npm run build"
  else
    echo "Aviso: npm não encontrado — o app não foi gerado (a API e o Telegram funcionam sem ele)." >&2
  fi
fi

rsync -a --delete --exclude .git --exclude node_modules --exclude '.venv' --exclude '__pycache__' \
  --exclude 'workspace/memoria' --exclude 'pw-browsers' --exclude '.claude/worktrees' "$REPO_DIR/" /opt/talos/
chown -R root:talos /opt/talos
chmod -R g+rX,o-rwx /opt/talos
chmod o+x /opt/talos   # o serviço talos precisa atravessar o diretório

# venv do core: dono talos (o uv escreve nele); o resto de /opt/talos fica só-leitura para o serviço
install -d -o talos -g talos -m 0750 /opt/talos/core/.venv
chown -R talos:talos /opt/talos/core/.venv
[[ -d /opt/talos/pw-browsers ]] && chown -R talos:talos /opt/talos/pw-browsers
as_talos bash -c 'cd /opt/talos/core && uv venv --allow-existing -q -p python3.12 .venv && uv sync --frozen --no-dev -q'

# workspace do agente: persona e skills vêm do git; memoria/ é dado de runtime (nunca sobrescrito)
install -d -o talos -g talos -m 0750 /srv/talos/workspace/memoria
rsync -a --delete --exclude memoria /opt/talos/workspace/ /srv/talos/workspace/
chown -R talos:talos /srv/talos/workspace

# chave do cofre: criada uma vez (como root, porque /etc/talos não é gravável pelo talos)
if [[ ! -f /etc/talos/vault.key ]]; then
  VAULT_KEY_FILE=/etc/talos/vault.key /opt/talos/core/.venv/bin/talos vault init
fi
chown talos:talos /etc/talos/vault.key && chmod 0600 /etc/talos/vault.key

as_talos bash -c 'set -a; . /etc/talos/secrets.env; set +a; /opt/talos/core/.venv/bin/talos migrate'

if [[ $RESTART -eq 1 ]] && command -v systemctl >/dev/null && [[ -d /run/systemd/system ]]; then
  systemctl restart talos-core.service
  systemctl --no-pager status talos-core.service | head -5
fi
echo "Deploy concluído."
