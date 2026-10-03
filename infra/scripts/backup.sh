#!/usr/bin/env bash
# Backup diário (SPEC §12.4): banco (sqlite3 .backup, inclui o cofre cifrado) + workspace/memoria.
# A chave do cofre NÃO vai no backup: guarde uma cópia de /etc/talos/vault.key fora do servidor.
set -euo pipefail
DATA=/var/lib/talos
OUT="$DATA/backups"
STAMP="$(date +%Y%m%d-%H%M)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

sqlite3 "$DATA/talos.db" ".backup '$TMP/talos.db'"
sqlite3 "$TMP/talos.db" "PRAGMA integrity_check" | grep -qx ok
cp -a /srv/talos/workspace/memoria "$TMP/memoria"
tar -C "$TMP" -czf "$OUT/talos-$STAMP.tar.gz" talos.db memoria
chmod 0600 "$OUT/talos-$STAMP.tar.gz"
find "$OUT" -name 'talos-*.tar.gz' -mtime +7 -delete
echo "$OUT/talos-$STAMP.tar.gz"

# Opcional (semanal): cópia cifrada com age para o Drive — ver RUNBOOK.md
if [[ -n "${AGE_RECIPIENT:-}" && "$(date +%u)" == "7" ]]; then
  age -r "$AGE_RECIPIENT" -o "$OUT/talos-$STAMP.tar.gz.age" "$OUT/talos-$STAMP.tar.gz"
fi

# screenshots dos cartões e snapshots do Playwright MCP: só 7 dias
find "$DATA/screens" -type f -mtime +7 -delete 2>/dev/null || true
