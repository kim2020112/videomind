#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

"$APP_DIR/deploy/backup.sh"
git -C "$APP_DIR" pull --ff-only
"$APP_DIR/.venv/bin/pip" install \
  -r "$APP_DIR/backend/requirements-core.txt" \
  -r "$APP_DIR/backend/requirements-ai.txt" \
  -r "$APP_DIR/backend/requirements-whisper.txt"
npm --prefix "$APP_DIR/frontend" ci
npm --prefix "$APP_DIR/frontend" run build

if command -v systemctl >/dev/null && [ "$(id -u)" -eq 0 ]; then
  systemctl restart videomind.service
  systemctl --no-pager status videomind.service
else
  echo "Build updated. Restart the VideoMind process to load the new version."
fi
