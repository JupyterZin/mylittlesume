#!/usr/bin/env bash
# /usr/local/bin/talos — atalho do CLI no servidor.
#   talos secrets set CHAVE   → como root (edita /etc/talos/secrets.env)
#   talos <outro comando>     → como o usuário talos, com os segredos carregados
set -euo pipefail
BIN=/opt/talos/core/.venv/bin/talos
cd /
if [[ "${1:-}" == "secrets" ]]; then
  [[ $EUID -eq 0 ]] || { echo "Use: sudo talos secrets ..."; exit 1; }
  exec "$BIN" "$@"
fi
exec sudo -u talos -H bash -c 'set -a; . /etc/talos/secrets.env; set +a; exec "$0" "$@"' "$BIN" "$@"
