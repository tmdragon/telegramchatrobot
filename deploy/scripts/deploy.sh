#!/usr/bin/env bash
# 升级脚本：在 VM 上 git pull → pip install → 重启
# 用法: sudo bash deploy/scripts/deploy.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "❌ 请用 root 跑: sudo bash $0" >&2
    exit 1
fi

APP_DIR="/opt/checkgprobot"
cd "$APP_DIR"

echo "=== git pull ==="
# 先备份 db（万一升级搞坏了能回滚）
ts=$(date +%Y%m%d-%H%M%S)
mkdir -p data/backups
if [[ -f data/checkgprobot.db ]]; then
    cp data/checkgprobot.db "data/backups/db-${ts}.bak"
    echo "📦 已备份到 data/backups/db-${ts}.bak"
fi

git pull --ff-only

echo "=== pip install ==="
.venv/bin/pip install -r requirements.txt

echo "=== 重启 checkgprobot ==="
systemctl restart checkgprobot

# 等几秒看进程是否起来
sleep 3
if systemctl is-active --quiet checkgprobot; then
    echo "✅ 服务起来了"
    echo "看日志: journalctl -u checkgprobot -n 50 -f"
else
    echo "❌ 服务挂了，看日志: journalctl -u checkgprobot -n 50 --no-pager"
    exit 1
fi