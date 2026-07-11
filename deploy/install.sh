#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
APP_USER="${APP_USER:-${SUDO_USER:-$USER}}"
PYTHON="${PYTHON:-python3.12}"
DATA_DIR="${DATA_DIR:-/var/lib/videomind}"

if ! id "$APP_USER" >/dev/null 2>&1; then
  if [ "$(id -u)" -ne 0 ]; then
    echo "User does not exist: $APP_USER" >&2
    exit 1
  fi
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
APP_GROUP="${APP_GROUP:-$(id -gn "$APP_USER")}"

command -v "$PYTHON" >/dev/null || { echo "Python 3.12 is required" >&2; exit 1; }
command -v npm >/dev/null || { echo "Node.js 22/npm is required for the frontend build" >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg is required" >&2; exit 1; }

"$PYTHON" -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install \
  -r "$APP_DIR/backend/requirements-core.txt" \
  -r "$APP_DIR/backend/requirements-ai.txt" \
  -r "$APP_DIR/backend/requirements-whisper.txt"

if [ ! -f "$APP_DIR/backend/.env" ]; then
  cp "$APP_DIR/backend/.env.example" "$APP_DIR/backend/.env"
  echo "Created backend/.env; set AI_API_KEY, ADMIN_PASSWORD, and GUEST_SECRET before public use."
fi

ENV_FILE="$APP_DIR/backend/.env"

has_env_key() {
  grep -Eq "^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=" "$ENV_FILE"
}

append_env_default() {
  if ! has_env_key "$1"; then
    printf '\n%s=%s\n' "$1" "$2" >> "$ENV_FILE"
  fi
}

mkdir -p \
  "$DATA_DIR/db" \
  "$DATA_DIR/temp" \
  "$DATA_DIR/downloads" \
  "$DATA_DIR/whisper_models" \
  "$DATA_DIR/backups"

# One-time migration for installations that used the old in-repository default.
# Explicit DB_PATH values are always preserved.
if ! has_env_key DB_PATH; then
  LEGACY_DB="$APP_DIR/backend/db/knowledge.db"
  TARGET_DB="$DATA_DIR/db/knowledge.db"
  if [ -f "$LEGACY_DB" ] && [ ! -f "$TARGET_DB" ]; then
    "$APP_DIR/.venv/bin/python" -c \
      'import sqlite3,sys; src=sqlite3.connect(sys.argv[1]); dst=sqlite3.connect(sys.argv[2]); src.backup(dst); dst.close(); src.close()' \
      "$LEGACY_DB" "$TARGET_DB"
    echo "Migrated SQLite database to: $TARGET_DB"
  fi
fi

if ! has_env_key AI_CONFIG_PATH; then
  LEGACY_AI_CONFIG="$APP_DIR/backend/data/ai_config.json"
  TARGET_AI_CONFIG="$DATA_DIR/ai_config.json"
  if [ -f "$LEGACY_AI_CONFIG" ] && [ ! -f "$TARGET_AI_CONFIG" ]; then
    cp "$LEGACY_AI_CONFIG" "$TARGET_AI_CONFIG"
    echo "Migrated AI configuration to: $TARGET_AI_CONFIG"
  fi
fi

append_env_default DATA_DIR "$DATA_DIR"
append_env_default DB_PATH "$DATA_DIR/db/knowledge.db"
append_env_default AI_CONFIG_PATH "$DATA_DIR/ai_config.json"
append_env_default TEMP_DIR "$DATA_DIR/temp"
append_env_default DOWNLOAD_DIR "$DATA_DIR/downloads"
append_env_default WHISPER_MODELS_DIR "$DATA_DIR/whisper_models"
append_env_default BACKUP_DIR "$DATA_DIR/backups"

if [ "$(id -u)" -eq 0 ]; then
  chown -R "$APP_USER:$APP_GROUP" "$DATA_DIR"
  chown "$APP_USER:$APP_GROUP" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

npm --prefix "$APP_DIR/frontend" ci
npm --prefix "$APP_DIR/frontend" run build
chmod +x "$APP_DIR"/deploy/*.sh "$APP_DIR/start.sh"

if command -v systemctl >/dev/null && [ "$(id -u)" -eq 0 ]; then
  sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__APP_USER__|$APP_USER|g" -e "s|__APP_GROUP__|$APP_GROUP|g" \
    "$APP_DIR/deploy/videomind.service" > /etc/systemd/system/videomind.service
  sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__APP_USER__|$APP_USER|g" -e "s|__APP_GROUP__|$APP_GROUP|g" \
    "$APP_DIR/deploy/videomind-maintenance.service" > /etc/systemd/system/videomind-maintenance.service
  cp "$APP_DIR/deploy/videomind-maintenance.timer" /etc/systemd/system/videomind-maintenance.timer
  systemctl daemon-reload
  systemctl enable --now videomind.service videomind-maintenance.timer
  systemctl --no-pager status videomind.service || true
else
  echo "Dependencies and frontend build are ready. Run this script as root to install systemd units."
fi

echo "VideoMind is available through 127.0.0.1:8000. Configure Caddy for public HTTPS."
echo "For a 4 GB server, a 2 GB swap file is recommended."
