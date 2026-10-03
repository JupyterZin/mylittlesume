#!/usr/bin/env bash
# Restauração (testada no RUNBOOK). Uso: sudo restore.sh /var/lib/talos/backups/talos-AAAAMMDD-HHMM.tar.gz
set -euo pipefail
FILE="${1:?indique o arquivo de backup}"
[[ $EUID -eq 0 ]] || { echo "Rode com sudo."; exit 1; }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
tar -C "$TMP" -xzf "$FILE"
sqlite3 "$TMP/talos.db" "PRAGMA integrity_check" | grep -qx ok || { echo "Backup corrompido."; exit 1; }

echo "Isto substitui o banco atual e a memória do Talos pelos do backup $FILE."
read -r -p "Digite SIM para continuar: " ok
[[ "$ok" == "SIM" ]] || { echo "Cancelado."; exit 1; }

systemctl stop talos-core.service
STAMP="$(date +%Y%m%d-%H%M%S)"
mv /var/lib/talos/talos.db "/var/lib/talos/talos.db.antes-restore-$STAMP" 2>/dev/null || true
rm -f /var/lib/talos/talos.db-wal /var/lib/talos/talos.db-shm
install -o talos -g talos -m 0600 "$TMP/talos.db" /var/lib/talos/talos.db
rsync -a --delete "$TMP/memoria/" /srv/talos/workspace/memoria/
chown -R talos:talos /srv/talos/workspace/memoria
systemctl start talos-core.service
echo "Restaurado. Rode 'make doctor'. O banco anterior ficou em /var/lib/talos/talos.db.antes-restore-$STAMP"
