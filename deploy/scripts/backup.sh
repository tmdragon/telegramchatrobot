#!/usr/bin/env bash
# 数据库备份 — 加 crontab 每天跑一次:
#   0 3 * * * /opt/checkgprobot/deploy/scripts/backup.sh
set -euo pipefail

APP_DIR="/opt/checkgprobot"
BACKUP_DIR="$APP_DIR/data/backups"
DB="$APP_DIR/data/checkgprobot.db"

mkdir -p "$BACKUP_DIR"

# 只保留最近 14 天
find "$BACKUP_DIR" -name "db-*.bak" -mtime +14 -delete

if [[ ! -f "$DB" ]]; then
    echo "no db at $DB, nothing to back up"
    exit 0
fi

ts=$(date +%Y%m%d-%H%M%S)
# SQLite 在线备份（不会锁 db）
sqlite3 "$DB" ".backup '$BACKUP_DIR/db-${ts}.bak'"
echo "backed up to $BACKUP_DIR/db-${ts}.bak"