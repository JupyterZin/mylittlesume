#!/usr/bin/env bash
# Bootstrap do servidor do Talos (SPEC §12.1). Idempotente: pode rodar várias vezes.
# Uso (como administrador com sudo):
#   sudo infra/scripts/bootstrap.sh base       # sistema, usuário talos, dependências, serviços
#   sudo infra/scripts/bootstrap.sh tailscale  # instala e liga o Tailscale (--ssh)
#   sudo infra/scripts/bootstrap.sh serve      # publica app e Tela só na tailnet
#   sudo infra/scripts/bootstrap.sh firewall   # PEDE CONFIRMAÇÃO: fecha tudo menos a tailnet
set -euo pipefail

STAGE="${1:-}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Os comandos que rodam como `talos` herdam o diretório atual; /root é 0700 e o npm falha com EACCES.
cd /
PW_MCP_VERSION="0.0.83"
NODE_MAJOR=22

log() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
need_root() { [[ $EUID -eq 0 ]] || { echo "Rode com sudo."; exit 1; }; }

stage_base() {
  log "1/7 Sistema atualizado, unattended-upgrades e fuso Europe/Lisbon"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get upgrade -y
  apt-get install -y unattended-upgrades ca-certificates curl git jq sqlite3 rsync age ufw sudo tzdata \
    python3.12 python3.12-venv xvfb x11-utils x11vnc novnc websockify fonts-noto fonts-noto-color-emoji
  dpkg-reconfigure -f noninteractive unattended-upgrades || true
  timedatectl set-timezone Europe/Lisbon 2>/dev/null || ln -sf /usr/share/zoneinfo/Europe/Lisbon /etc/localtime

  log "2/7 Usuário de sistema talos (sem shell de login, sem sudo) e diretórios"
  if ! id talos >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/talos --shell /usr/sbin/nologin --user-group talos
  fi
  install -d -o root  -g talos -m 0755 /opt/talos
  install -d -o talos -g talos -m 0750 /srv/talos /srv/talos/workspace /srv/talos/workspace/memoria
  install -d -o talos -g talos -m 0750 /var/lib/talos /var/lib/talos/backups /var/lib/talos/screens
  install -d -o talos -g talos -m 0700 /var/lib/talos/browser-profile
  install -d -o root  -g talos -m 0750 /etc/talos
  if [[ ! -f /etc/talos/secrets.env ]]; then
    install -o talos -g talos -m 0600 "$REPO_DIR/.env.example" /etc/talos/secrets.env
    echo "Criei /etc/talos/secrets.env a partir do .env.example (preencha depois)."
  fi
  chown talos:talos /etc/talos/secrets.env && chmod 0600 /etc/talos/secrets.env

  log "3/7 uv, Node ${NODE_MAJOR} e Claude Code CLI (instalador nativo)"
  if ! command -v uv >/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
  fi
  if ! command -v node >/dev/null || [[ "$(node -v | cut -c2- | cut -d. -f1)" -lt $NODE_MAJOR ]]; then
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
    apt-get install -y nodejs
  fi
  # CLI para o administrador (claude setup-token) e para o talos (teste `claude -p`)
  ADMIN="${SUDO_USER:-root}"
  sudo -u "$ADMIN" -H bash -c 'command -v claude >/dev/null || curl -fsSL https://claude.ai/install.sh | bash'
  sudo -u talos -H bash -c 'test -x ~/.local/bin/claude || curl -fsSL https://claude.ai/install.sh | bash'

  log "4/7 Chromium do Playwright (com dependências) e Playwright MCP ${PW_MCP_VERSION}"
  install -d -o talos -g talos -m 0755 /opt/talos/pw-browsers
  PLAYWRIGHT_BROWSERS_PATH=/opt/talos/pw-browsers npx -y playwright@latest install-deps chromium
  sudo -u talos -H env PLAYWRIGHT_BROWSERS_PATH=/opt/talos/pw-browsers npx -y playwright@latest install chromium
  sudo -u talos -H npx -y "@playwright/mcp@${PW_MCP_VERSION}" --help >/dev/null
  # Ubuntu 24.04 restringe user namespaces sem privilégio; o sandbox do Chromium precisa deles.
  # Em vez de --no-sandbox, damos a permissão só a este binário (como o Ubuntu faz para o Chrome).
  if [[ -d /etc/apparmor.d ]] && command -v apparmor_parser >/dev/null; then
    cat > /etc/apparmor.d/talos-chrome <<'AA'
abi <abi/4.0>,
include <tunables/global>

profile talos-chrome /opt/talos/pw-browsers/chromium-*/chrome-linux*/chrome flags=(unconfined) {
  userns,
  include if exists <local/talos-chrome>
}
AA
    apparmor_parser -r /etc/apparmor.d/talos-chrome || echo "AVISO: não carreguei o perfil AppArmor do Chromium"
  fi

  log "5/7 Senha do VNC (a Tela só é acessível pela tailnet, mas não fica aberta)"
  if [[ ! -f /etc/talos/vnc.pass ]]; then
    PASS="$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 8)"
    x11vnc -storepasswd "$PASS" /etc/talos/vnc.pass >/dev/null
    chown talos:talos /etc/talos/vnc.pass && chmod 0600 /etc/talos/vnc.pass
    echo "Senha da Tela (noVNC): $PASS   ← guarde no seu gestor de senhas; não é mostrada de novo."
  fi

  log "6/7 Código em /opt/talos e ambiente Python"
  "$REPO_DIR/infra/scripts/deploy.sh" --no-restart

  log "7/7 Serviços systemd"
  if [[ ! -d /run/systemd/system ]]; then
    echo "Sem systemd (contêiner de teste?): serviços não instalados."
    return 0
  fi
  install -m 0644 "$REPO_DIR"/infra/systemd/talos-*.service "$REPO_DIR"/infra/systemd/talos-*.timer /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable talos-browser.service talos-novnc.service talos-core.service talos-backup.timer
  systemctl restart talos-browser.service talos-novnc.service
  systemctl start talos-backup.timer
  echo "talos-core fica parado até /etc/talos/secrets.env estar preenchido. Depois: sudo systemctl start talos-core"
  if command -v pre-commit >/dev/null && [[ -d "$REPO_DIR/.git" ]]; then
    (cd "$REPO_DIR" && sudo -u "$ADMIN" pre-commit install) || true
  fi
}

stage_tailscale() {
  log "Tailscale com SSH da tailnet"
  command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
  tailscale up --ssh --hostname=talos
  tailscale status | head -5
  echo "Teste AGORA, de outro terminal: ssh <seu-usuario>@talos (pela tailnet). Só depois rode o estágio firewall."
}

stage_serve() {
  log "Publicando só na tailnet: app (/) e Tela (/tela)"
  tailscale serve --bg --https=443 http://127.0.0.1:8000
  tailscale serve --bg --https=443 --set-path=/tela http://127.0.0.1:6080
  tailscale serve status
  DNS="$(tailscale status --json | jq -r '.Self.DNSName' | sed 's/\.$//')"
  sudo -u talos sqlite3 /var/lib/talos/talos.db \
    "INSERT INTO system_state(key, value_json, updated_at) VALUES('app', json_object('url','https://$DNS'), datetime('now'))
     ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json" 2>/dev/null || true
  echo "App: https://$DNS  ·  Tela: https://$DNS/tela/vnc.html?path=tela/websockify&autoconnect=1&resize=scale"
}

stage_firewall() {
  log "Firewall: só a interface tailscale0 entra"
  tailscale status >/dev/null || { echo "Tailscale não está ligado. Rode o estágio tailscale primeiro."; exit 1; }
  echo "ATENÇÃO: isto fecha o SSH público. Se o SSH pela tailnet não estiver a funcionar, você perde o acesso"
  echo "(nesse caso, só pelo console web da Hostinger)."
  read -r -p "Já entrou com sucesso via 'ssh <usuario>@talos' pela tailnet? Digite SIM para continuar: " ok
  [[ "$ok" == "SIM" ]] || { echo "Cancelado. Nada mudou."; exit 1; }
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow in on tailscale0
  ufw --force enable
  ufw delete allow OpenSSH 2>/dev/null || true
  ufw delete allow 22/tcp 2>/dev/null || true
  ufw status verbose
  echo "Verifique: ss -tlnp (só 127.0.0.1 e a tailnet) e um scan externo ao IP público."
}

need_root
case "$STAGE" in
  base) stage_base ;;
  tailscale) stage_tailscale ;;
  serve) stage_serve ;;
  firewall) stage_firewall ;;
  *) echo "Uso: sudo $0 base|tailscale|serve|firewall"; exit 1 ;;
esac
