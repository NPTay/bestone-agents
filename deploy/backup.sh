#!/usr/bin/env bash
# Daily Postgres backup. Run from the repo root: deploy/backup.sh
# Keeps 7 daily + 4 weekly (Sunday) dumps locally; uploads to S3 when BACKUP_S3_* are set.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] || { echo "backup: .env not found" >&2; exit 1; }

# Read only the variables we need from .env (never echo them).
env_get() { grep -E "^$1=" .env | tail -n1 | cut -d= -f2- | tr -d '\r' || true; }
POSTGRES_USER="$(env_get POSTGRES_USER)"
POSTGRES_DB="$(env_get POSTGRES_DB)"
BACKUP_S3_ENDPOINT="$(env_get BACKUP_S3_ENDPOINT)"
BACKUP_S3_BUCKET="$(env_get BACKUP_S3_BUCKET)"
BACKUP_S3_ACCESS_KEY="$(env_get BACKUP_S3_ACCESS_KEY)"
BACKUP_S3_SECRET_KEY="$(env_get BACKUP_S3_SECRET_KEY)"
: "${POSTGRES_USER:?POSTGRES_USER missing in .env}"
: "${POSTGRES_DB:?POSTGRES_DB missing in .env}"

COMPOSE=(docker compose -f deploy/docker-compose.yml --env-file .env)
BACKUP_DIR="backups"
mkdir -p "$BACKUP_DIR/weekly"

STAMP="$(date +%Y%m%d-%H%M)"
FILE="$BACKUP_DIR/bestone-$STAMP.dump"
TMP="$FILE.partial"

if ! "${COMPOSE[@]}" exec -T db pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > "$TMP"; then
  rm -f "$TMP"
  echo "backup: pg_dump failed" >&2
  exit 1
fi
if [ ! -s "$TMP" ]; then
  rm -f "$TMP"
  echo "backup: dump is empty" >&2
  exit 1
fi
mv "$TMP" "$FILE"
echo "backup: wrote $FILE"

# Sunday dumps are also kept as weekly copies.
if [ "$(date +%u)" = "7" ]; then
  cp "$FILE" "$BACKUP_DIR/weekly/"
fi

# Retention: keep the newest $2 dumps in directory $1.
prune() {
  local f
  while IFS= read -r f; do
    [ -n "$f" ] && rm -f -- "$f"
  done < <(ls -1t "$1"/bestone-*.dump 2>/dev/null | tail -n +"$(($2 + 1))")
  return 0
}
prune "$BACKUP_DIR" 7
prune "$BACKUP_DIR/weekly" 4

# Off-site copy (only when all S3 settings are present).
if [ -n "$BACKUP_S3_ENDPOINT" ] && [ -n "$BACKUP_S3_BUCKET" ] \
  && [ -n "$BACKUP_S3_ACCESS_KEY" ] && [ -n "$BACKUP_S3_SECRET_KEY" ]; then
  docker run --rm \
    -e AWS_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY" \
    -e AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_KEY" \
    -e AWS_DEFAULT_REGION=us-east-1 \
    -v "$PWD/$BACKUP_DIR:/backups:ro" \
    amazon/aws-cli s3 cp "/backups/$(basename "$FILE")" \
    "s3://$BACKUP_S3_BUCKET/$(basename "$FILE")" \
    --endpoint-url "$BACKUP_S3_ENDPOINT"
  echo "backup: uploaded to S3"
else
  echo "backup: BACKUP_S3_* not fully set, skipping off-site upload" >&2
fi
