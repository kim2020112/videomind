#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-$APP_DIR/backend/.env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

DATA_DIR="${DATA_DIR:-/var/lib/videomind}"
DB_PATH="${DB_PATH:-$DATA_DIR/db/knowledge.db}"
BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
PYTHON="${PYTHON:-$APP_DIR/.venv/bin/python}"

mkdir -p "$BACKUP_DIR"
if [ ! -f "$DB_PATH" ]; then
  echo "Database does not exist yet: $DB_PATH"
  exit 0
fi

DEST="$BACKUP_DIR/knowledge-$(date +%Y%m%d-%H%M%S).db"
"$PYTHON" -c 'import sqlite3,sys; src=sqlite3.connect(sys.argv[1]); dst=sqlite3.connect(sys.argv[2]); src.backup(dst); dst.close(); src.close()' "$DB_PATH" "$DEST"
find "$BACKUP_DIR" -type f -name 'knowledge-*.db' -mtime "+$BACKUP_RETENTION_DAYS" -delete
echo "Backup created: $DEST"
