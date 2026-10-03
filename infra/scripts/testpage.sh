#!/usr/bin/env bash
# Serve as páginas de teste locais (infra/testpages) em 127.0.0.1:9000 — teste de aceitação da Fase 4
# (SPEC §14): http://127.0.0.1:9000/formulario.html. Só loopback; Ctrl+C para parar.
#   PORT=9001 infra/scripts/testpage.sh   # outra porta
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../testpages" && pwd)"
PORT="${PORT:-9000}"
PY="$(command -v python3.12 || command -v python3)"
echo "Formulário de teste: http://127.0.0.1:${PORT}/formulario.html"
exec "$PY" -m http.server "$PORT" --bind 127.0.0.1 --directory "$DIR"
