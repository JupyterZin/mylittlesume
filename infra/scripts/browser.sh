#!/usr/bin/env bash
# Xvfb :99 + Chromium persistente com CDP só em 127.0.0.1 (SPEC §12.2).
set -euo pipefail
export DISPLAY=:99
PROFILE=/var/lib/talos/browser-profile
CHROME="$(find "${PLAYWRIGHT_BROWSERS_PATH:-/opt/talos/pw-browsers}" -type f -name chrome -path '*chrome-linux*' | head -1)"
[[ -x "$CHROME" ]] || { echo "Chromium do Playwright não encontrado"; exit 1; }

Xvfb :99 -screen 0 1280x900x24 -nolisten tcp &
XVFB=$!
trap 'kill $XVFB 2>/dev/null || true' EXIT
for _ in $(seq 1 50); do xdpyinfo -display :99 >/dev/null 2>&1 && break; sleep 0.1; done

# o Chromium pode ter ficado com o lock do perfil depois de um crash
rm -f "$PROFILE"/SingletonLock "$PROFILE"/SingletonSocket "$PROFILE"/SingletonCookie
"$CHROME" --user-data-dir="$PROFILE" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
  --no-first-run --no-default-browser-check --disable-dev-shm-usage --lang=pt-PT \
  --window-size=1280,900 --window-position=0,0 --password-store=basic about:blank
