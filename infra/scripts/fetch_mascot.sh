#!/usr/bin/env bash
# Baixa de novo o mascote (RobotExpressive, CC0 1.0 — Tomás Laulhé/Quaternius, modificado por
# Don McCurdy) do repositório do three.js para app/public/assets/talos.glb e confere o SHA-256.
# O arquivo já vem no git; use isto só para restaurá-lo ou conferir a origem.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="$REPO_DIR/app/public/assets/talos.glb"
URL="https://raw.githubusercontent.com/mrdoob/three.js/dev/examples/models/gltf/RobotExpressive/RobotExpressive.glb"
SHA256="047f5e5fb3bb6d378bd1df16ca6137f2a596c99b3a1b5690b4020c05aaf6f319"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsSL --retry 3 -o "$tmp" "$URL"
got="$(sha256sum "$tmp" | cut -d' ' -f1)"
if [[ "$got" != "$SHA256" ]]; then
  echo "SHA-256 diferente do esperado ($got). O arquivo no three.js pode ter mudado; confira antes de usar." >&2
  exit 1
fi
install -D -m 0644 "$tmp" "$DEST"
echo "Mascote em $DEST ($(stat -c %s "$DEST") bytes). Gere as poses 2D com: cd app && npm run build && npm run poses"
