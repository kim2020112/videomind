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
TEMP_DIR="${TEMP_DIR:-$DATA_DIR/temp}"
DOWNLOAD_DIR="${DOWNLOAD_DIR:-$DATA_DIR/downloads}"
TEMP_RETENTION_DAYS="${TEMP_RETENTION_DAYS:-2}"
DOWNLOAD_RETENTION_DAYS="${DOWNLOAD_RETENTION_DAYS:-14}"

for dir in "$TEMP_DIR" "$DOWNLOAD_DIR"; do
  mkdir -p "$dir"
done

find "$TEMP_DIR" -mindepth 1 -type f -mtime "+$TEMP_RETENTION_DAYS" -delete
find "$TEMP_DIR" -mindepth 1 -depth -type d -empty -delete
find "$DOWNLOAD_DIR" -mindepth 1 -type f -mtime "+$DOWNLOAD_RETENTION_DAYS" -delete
find "$DOWNLOAD_DIR" -mindepth 1 -depth -type d -empty -delete
echo "Cleanup complete"
