#!/usr/bin/env bash
# checkGPRobot 首次部署脚本 — Ubuntu 22.04 LTS（阿里云轻量 / 海外 VM 都通用）
#
# 用法:
#   有域名 + HTTPS:  sudo bash setup.sh <DOMAIN> <EMAIL>
#     例: sudo bash setup.sh check.example.com you@example.com
#     需要先在 DNS 服务商把 A 记录指向 VM 公网 IP
#
#   无域名 + HTTP:   sudo bash setup.sh --no-domain
#     访问 http://<VM公网IP>/，Basic Auth 密码明文传输（自用够）
#
# 前置条件:
#   1. 项目已 git clone 到 /opt/checkgprobot（或代码已 scp 进去）
#   2. /etc/checkgprobot/gcp-sa.json 已就位（chmod 600）
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "❌ 请用 root 跑: sudo bash $0" >&2
    exit 1
fi

MODE=""
DOMAIN=""
EMAIL=""

case "${1:-}" in
    --no-domain)
        MODE="http"
        ;;
    -h|--help|"")
        cat <<EOF
用法:
  sudo bash $0 <DOMAIN> <EMAIL>    # HTTPS 模式(需要域名 + DNS A 记录)
  sudo bash $0 --no-domain         # HTTP 模式(只用 IP 直接访问)
EOF
        exit 0
        ;;
    *)
        if [[ $# -ge 2 ]]; then
            MODE="https"
            DOMAIN="$1"
            EMAIL="$2"
        else
            echo "❌ HTTPS 模式需要两个参数: DOMAIN EMAIL" >&2
            exit 1
        fi
        ;;
esac

APP_DIR="/opt/checkgprobot"
ETC_DIR="/etc/checkgprobot"

if [[ ! -d "$APP_DIR" ]]; then
    echo "❌ 找不到 $APP_DIR，请先把项目 git clone 到那里" >&2
    exit 1
fi

if [[ ! -f "$ETC_DIR/gcp-sa.json" ]]; then
    echo "❌ 找不到 $ETC_DIR/gcp-sa.json，请先把 GCP service account JSON 上传过来：" >&2
    echo "   sudo mkdir -p $ETC_DIR && sudo chmod 700 $ETC_DIR" >&2
    echo "   sudo cp /local/path/gcp-sa.json $ETC_DIR/gcp-sa.json" >&2
    echo "   sudo chmod 600 $ETC_DIR/gcp-sa.json" >&2
    exit 1
fi

echo "=== 部署模式: ${MODE^^} ==="
echo

echo "=== 1/8 装系统包 ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
if [[ "$MODE" == "https" ]]; then
    apt-get install -y --no-install-recommends \
        nginx certbot python3-certbot-nginx python3-venv python3-pip apache2-utils
else
    apt-get install -y --no-install-recommends \
        nginx python3-venv python3-pip apache2-utils
fi

echo "=== 2/8 建目录 ==="
mkdir -p "$ETC_DIR"
chmod 700 "$ETC_DIR"
mkdir -p "$APP_DIR/data" "$APP_DIR/data/backups"
chmod 750 "$APP_DIR/data"

echo "=== 3/8 Python venv ==="
if [[ ! -d "$APP_DIR/.venv" ]]; then
    python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "=== 4/8 secrets.yaml ==="
if [[ ! -f "$ETC_DIR/secrets.yaml" ]]; then
    cp "$APP_DIR/config/secrets.yaml.example" "$ETC_DIR/secrets.yaml"
    sed -i 's|google_service_account_json: "data/credentials/gcp-sa.json"|google_service_account_json: "/etc/checkgprobot/gcp-sa.json"|' "$ETC_DIR/secrets.yaml"
    echo "📝 生成 $ETC_DIR/secrets.yaml — 请编辑 telegram_bot_token / admin_chat_id:"
    echo "   nano $ETC_DIR/secrets.yaml"
fi
chmod 600 "$ETC_DIR/secrets.yaml"

echo "=== 5/8 sheets.yaml ==="
if [[ ! -f "$ETC_DIR/sheets.yaml" ]]; then
    cp "$APP_DIR/config/sheets.yaml.example" "$ETC_DIR/sheets.yaml"
    echo "📝 生成 $ETC_DIR/sheets.yaml — 请编辑 spreadsheet id/name/role:"
    echo "   nano $ETC_DIR/sheets.yaml"
fi
chmod 644 "$ETC_DIR/sheets.yaml"

echo "=== 6/8 secrets.env ==="
if [[ ! -f "$ETC_DIR/secrets.env" ]]; then
    cat > "$ETC_DIR/secrets.env" <<EOF
# systemd EnvironmentFile 格式(每行 KEY=VALUE,不要引号)。
# 留空时 app 会 fallback 到 secrets.yaml。
# CHECKGPROBOT_TELEGRAM_BOT_TOKEN=
# CHECKGPROBOT_ADMIN_CHAT_ID=
# GOOGLE_APPLICATION_CREDENTIALS=/etc/checkgprobot/gcp-sa.json
EOF
    chmod 600 "$ETC_DIR/secrets.env"
fi

echo "=== 7/8 Basic Auth ==="
if [[ ! -f /etc/nginx/.htpasswd ]]; then
    echo "📝 创建 Web UI 登录用户名密码:"
    htpasswd -c /etc/nginx/.htpasswd admin
    chmod 640 /etc/nginx/.htpasswd
fi

echo "=== 8/8 systemd + nginx ==="
cp "$APP_DIR/deploy/systemd/checkgprobot.service" /etc/systemd/system/checkgprobot.service
systemctl daemon-reload
systemctl enable checkgprobot.service
systemctl restart checkgprobot.service

# nginx: 按模式选模板
if [[ "$MODE" == "https" ]]; then
    sed "s/YOUR_DOMAIN/${DOMAIN}/g" "$APP_DIR/deploy/nginx/checkgprobot.conf" \
        > /etc/nginx/sites-available/checkgprobot
else
    cp "$APP_DIR/deploy/nginx/checkgprobot-http.conf" \
        /etc/nginx/sites-available/checkgprobot
fi
ln -sf /etc/nginx/sites-available/checkgprobot /etc/nginx/sites-enabled/checkgprobot
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl reload nginx

if [[ "$MODE" == "https" ]]; then
    echo "=== 8/8 Let's Encrypt 证书 ==="
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect
fi

# 取 VM 公网 IP（仅 http 模式用得到；失败时给个 fallback）
PUBLIC_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null \
            || curl -s --max-time 5 https://ifconfig.me 2>/dev/null \
            || echo "<VM 公网 IP>")

echo
echo "✅ 部署完成（${MODE^^} 模式）"
echo
echo "下一步："
echo "  1. 编辑 secrets 真实值:  nano $ETC_DIR/secrets.yaml"
echo "  2. 编辑 sheets 配置:     nano $ETC_DIR/sheets.yaml"
echo "  3. 重启服务:             systemctl restart checkgprobot"
echo "  4. 看日志:               journalctl -u checkgprobot -f"
if [[ "$MODE" == "https" ]]; then
    echo "  5. 打开 Web:             https://$DOMAIN/  (Basic Auth 用户名密码)"
else
    echo "  5. 打开 Web:             http://${PUBLIC_IP}/  (Basic Auth 用户名密码)"
    echo
    echo "  注: HTTP 模式密码明文传输，自用足够。"
    echo "  以后买了域名重跑: bash $APP_DIR/deploy/scripts/setup.sh your.domain.com you@example.com"
fi
echo
echo "日后升级：cd $APP_DIR && sudo bash deploy/scripts/deploy.sh"