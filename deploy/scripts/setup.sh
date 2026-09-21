#!/usr/bin/env bash
# checkGPRobot 首次部署脚本 — 阿里云国内版 / 香港节点 / Ubuntu 22.04 LTS
# 用法: sudo bash deploy/scripts/setup.sh YOUR_DOMAIN admin@example.com
#   YOUR_DOMAIN: 域名（如 check.example.com；先用 DNS A 记录指到 VM 公网 IP）
#   EMAIL:       证书注册邮箱（Let's Encrypt 用）
#
# 前置条件:
#   1. 已 git clone 到 /opt/checkgprobot（或修改 APP_DIR）
#   2. /etc/checkgprobot/gcp-sa.json 已通过 scp 上传（GCP service account JSON）
#   3. DNS A 记录已指到 VM IP
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "❌ 请用 root 跑: sudo bash $0" >&2
    exit 1
fi

DOMAIN="${1:-}"
EMAIL="${2:-}"
APP_DIR="/opt/checkgprobot"
ETC_DIR="/etc/checkgprobot"

if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
    echo "用法: sudo bash $0 <DOMAIN> <EMAIL>" >&2
    echo "  DOMAIN: 形如 check.example.com（DNS A 记录要先指向 VM）" >&2
    echo "  EMAIL:  Let's Encrypt 注册邮箱" >&2
    exit 1
fi

if [[ ! -d "$APP_DIR" ]]; then
    echo "❌ 找不到 $APP_DIR，请先把项目 git clone 到那里：" >&2
    echo "   git clone <repo-url> $APP_DIR" >&2
    exit 1
fi

if [[ ! -f "$ETC_DIR/gcp-sa.json" ]]; then
    echo "❌ 找不到 $ETC_DIR/gcp-sa.json，请先把 GCP service account JSON 上传过来：" >&2
    echo "   sudo mkdir -p $ETC_DIR && sudo chmod 700 $ETC_DIR" >&2
    echo "   sudo cp /local/path/gcp-sa.json $ETC_DIR/gcp-sa.json" >&2
    echo "   sudo chmod 600 $ETC_DIR/gcp-sa.json && sudo chown root:root $ETC_DIR/gcp-sa.json" >&2
    exit 1
fi

echo "=== 1/8 装系统包 ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y --no-install-recommends nginx certbot python3-certbot-nginx python3-venv python3-pip apache2-utils

echo "=== 2/8 建目录 ==="
mkdir -p "$ETC_DIR"
chmod 700 "$ETC_DIR"

# 数据目录
mkdir -p "$APP_DIR/data" "$APP_DIR/data/backups"
chmod 750 "$APP_DIR/data"

echo "=== 3/8 Python venv ==="
if [[ ! -d "$APP_DIR/.venv" ]]; then
    sudo -u root python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "=== 4/8 secrets.yaml（只首次运行） ==="
if [[ ! -f "$ETC_DIR/secrets.yaml" ]]; then
    cp "$APP_DIR/config/secrets.yaml.example" "$ETC_DIR/secrets.yaml"
    # 让 gcp-sa 路径指向 /etc/checkgprobot/
    sed -i 's|google_service_account_json: "data/credentials/gcp-sa.json"|google_service_account_json: "/etc/checkgprobot/gcp-sa.json"|' "$ETC_DIR/secrets.yaml"
    sed -i 's|ui_bind: "127.0.0.1"|ui_bind: "127.0.0.1"|' "$ETC_DIR/secrets.yaml"
    echo "📝 生成 $ETC_DIR/secrets.yaml — 请手动编辑 telegram_bot_token / admin_chat_id 等真实值："
    echo "   sudo nano $ETC_DIR/secrets.yaml"
    echo "完成后重新跑: sudo systemctl restart checkgprobot"
    # 不要让 setup 因为未填的 token 卡住；服务起不来 user 自己看 journald
fi
chmod 600 "$ETC_DIR/secrets.yaml"

echo "=== 5/8 sheets.yaml（只首次运行） ==="
if [[ ! -f "$ETC_DIR/sheets.yaml" ]]; then
    cp "$APP_DIR/config/sheets.yaml.example" "$ETC_DIR/sheets.yaml"
    echo "📝 生成 $ETC_DIR/sheets.yaml — 请编辑 spreadsheet id/name/role："
    echo "   sudo nano $ETC_DIR/sheets.yaml"
fi
chmod 644 "$ETC_DIR/sheets.yaml"

echo "=== 6/8 secrets.env（systemd EnvironmentFile，可选） ==="
if [[ ! -f "$ETC_DIR/secrets.env" ]]; then
    cat > "$ETC_DIR/secrets.env" <<EOF
# systemd EnvironmentFile 格式（每行 KEY=VALUE，不要引号）。
# 留空时 app 会 fallback 到 secrets.yaml。
# 典型用途：CI 覆盖 / docker 化迁移时切换。
# CHECKGPROBOT_TELEGRAM_BOT_TOKEN=
# CHECKGPROBOT_ADMIN_CHAT_ID=
# GOOGLE_APPLICATION_CREDENTIALS=/etc/checkgprobot/gcp-sa.json
EOF
    chmod 600 "$ETC_DIR/secrets.env"
fi

echo "=== 7/8 Basic Auth ==="
if [[ ! -f /etc/nginx/.htpasswd ]]; then
    echo "📝 创建 Web UI 登录用户名密码（输完直接回车）："
    htpasswd -c /etc/nginx/.htpasswd admin
    chmod 640 /etc/nginx/.htpasswd
fi

echo "=== 8/8 systemd + nginx ==="
cp "$APP_DIR/deploy/systemd/checkgprobot.service" /etc/systemd/system/checkgprobot.service
systemctl daemon-reload
systemctl enable checkgprobot.service
systemctl restart checkgprobot.service

# nginx：用 sed 替换占位的域名
sed "s/YOUR_DOMAIN/${DOMAIN}/g" "$APP_DIR/deploy/nginx/checkgprobot.conf" > /etc/nginx/sites-available/checkgprobot
ln -sf /etc/nginx/sites-available/checkgprobot /etc/nginx/sites-enabled/checkgprobot
# 删掉默认站（如果存在），避免冲突
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl reload nginx

echo "=== Let's Encrypt 证书 ==="
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect

echo
echo "✅ 部署完成！"
echo
echo "下一步："
echo "  1. 编辑 secrets 真实值:  sudo nano $ETC_DIR/secrets.yaml"
echo "  2. 编辑 sheets 配置:     sudo nano $ETC_DIR/sheets.yaml"
echo "  3. 重启服务:             sudo systemctl restart checkgprobot"
echo "  4. 看日志:               sudo journalctl -u checkgprobot -f"
echo "  5. 打开 Web:             https://$DOMAIN/  （用户名密码就是 htpasswd 那个）"
echo
echo "如需日后升级：cd $APP_DIR && sudo bash deploy/scripts/deploy.sh"