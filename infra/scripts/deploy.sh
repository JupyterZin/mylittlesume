#!/usr/bin/env bash
# Copia o repositório para /opt/talos, prepara o venv e o workspace do agente, aplica migrações.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RESTART=1
[[ "${1:-}" == "--no-restart" ]] && RESTART=0
[[ $EUID -eq 0 ]] || { echo "Rode com sudo."; exit 1; }

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
  --exclude 'workspace/memoria' --exclude 'pw-browsers' "$REPO_DIR/" /opt/talos/
chown -R root:talos /opt/talos && chmod -R g+rX,o-rwx /opt/talos
chown -R talos:talos /opt/talos/pw-browsers 2>/dev/null || true

# venv do core (dono talos para o uv poder escrever; o serviço vê /opt só-leitura)
install -d -o talos -g talos /opt/talos/core/.venv
sudo -u talos -H bash -c 'cd /opt/talos/core && uv sync --frozen --no-dev -p python3.12'

# workspace do agente: persona e skills vêm do git; memoria/ é dado de runtime (nunca sobrescrito)
rsync -a --delete --exclude memoria /opt/talos/workspace/ /srv/talos/workspace/
chown -R talos:talos /srv/talos/workspace

sudo -u talos -H bash -c 'set -a; . /etc/talos/secrets.env; set +a; /opt/talos/core/.venv/bin/talos vault init && /opt/talos/core/.venv/bin/talos migrate'
if [[ $RESTART -eq 1 ]]; then
  systemctl restart talos-core.service
  systemctl --no-pager status talos-core.service | head -5
fi
