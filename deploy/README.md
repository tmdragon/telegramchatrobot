# 部署到阿里云国内版 (轻量应用服务器 / Ubuntu 22.04 LTS)

本目录包含生产环境部署用的所有文件,**不**依赖 docker / k8s —— 单 VM + systemd + nginx。

> 本文档对应 [aliyun.com](https://www.aliyun.com/) 国内版(不是国际版 alibabacloud.com)。
> 节点选**香港**(免 ICP 备案,当晚可上线);大陆节点需要先做 ICP 备案(7-20 天)。

## 一次性部署

### 1. 在阿里云国内版控制台创建实例

1. 登录 [阿里云国内版](https://www.aliyun.com/) → **轻量应用服务器** → **立即购买** / **创建**
2. 区域选 **香港**(免备案,个人项目推荐)
3. 镜像选 **Ubuntu 22.04 LTS**
4. 套餐选最便宜的(轻量应用服务器 2核2G 约 ¥28-35/月,新用户首年 ¥24)
5. 设置 root 密码或 SSH key
6. **创建**后等待 1-3 分钟开机

### 2. 拿公网 IP

轻量应用服务器创建后**自动分配一个固定公网 IP**(与实例绑定),不会因重启变化。可以在控制台"服务器"→ 你的实例 → **服务器详情** → "网络"看到。

> 阿里云国内版的轻量**不需要单独买 EIP**——这是跟国际版 / ECS 的一个区别。

### 3. DNS A 记录

把你的域名(如 `check.example.com`)的 A 记录指向那个公网 IP。

### 4. 准备 GCP 凭据 + 部署

阿里云轻量默认 SSH 用户是 **root**,可以直接登。

```bash
# 把 GCP service account JSON 拷到 VM
scp gcp-sa.json root@<公网IP>:~/

ssh root@<公网IP>

# 装 git（Ubuntu 镜像通常自带，没带的话）
apt update && apt install -y git

# clone 项目
git clone <repo-url> /opt/checkgprobot
cd /opt/checkgprobot

# 准备凭据目录
mkdir -p /etc/checkgprobot && chmod 700 /etc/checkgprobot
mv /root/gcp-sa.json /etc/checkgprobot/gcp-sa.json
chmod 600 /etc/checkgprobot/gcp-sa.json

# 跑 setup
bash deploy/scripts/setup.sh your.domain.com you@example.com

# 按提示编辑真实 secrets 和 sheets 配置
nano /etc/checkgprobot/secrets.yaml
nano /etc/checkgprobot/sheets.yaml
systemctl restart checkgprobot
```

### 5. 防火墙验证(轻量自带)

阿里云**轻量应用服务器**自带防火墙,默认**已开放** 80/443/22,通常不用改。如果 443 不通:

控制台 → 轻量应用服务器 → 你的实例 → **防火墙** → 添加规则:

| 端口 | 协议 | 用途 |
|---|---|---|
| 22 | TCP | SSH |
| 80 | TCP | HTTP(certbot 验证 + 重定向) |
| 443 | TCP | HTTPS |

> **为什么不用 Ubuntu 自带 `ufw`?** 轻量防火墙在实例外面(更安全)。

### 6. 阿里云安全组(可选)

如果你之后想换到 ECS 实例,需要单独配**安全组**。轻量服务器不需要。

## 文件说明

| 文件 | 部署到 VM 的位置 | 用途 |
|------|-----------------|------|
| `systemd/checkgprobot.service` | `/etc/systemd/system/` | systemd unit,`Restart=always`,走 `secrets.env` |
| `nginx/checkgprobot.conf` | `/etc/nginx/sites-available/` | 443 反代 + Basic Auth;`setup.sh` 自动替换域名 |
| `scripts/setup.sh` | — | 首次部署:装包、建 venv、注册 systemd、申请证书 |
| `scripts/deploy.sh` | — | 升级:`git pull` + `pip install` + `systemctl restart` |
| `scripts/backup.sh` | cron / 手动 | SQLite 在线备份到 `data/backups/`,保留 14 天 |

## 升级流程

```bash
ssh root@<公网IP>
cd /opt/checkgprobot
sudo bash deploy/scripts/deploy.sh
```

## 加每日数据库备份

```bash
ssh root@<公网IP> 'sudo crontab -e'
# 加这一行:
# 0 3 * * * /opt/checkgprobot/deploy/scripts/backup.sh
```

## 排错

```bash
# 看应用日志
sudo journalctl -u checkgprobot -f

# 看 nginx 错误
sudo tail -f /var/log/nginx/error.log

# 重启某项
sudo systemctl restart checkgprobot
sudo systemctl reload nginx

# 检查端口（应用只监听 127.0.0.1:8765；公网入口是 nginx）
ss -ltnp | grep -E '8765|443|80'
```

## 密钥覆盖优先级(从高到低)

1. **systemd EnvironmentFile** (`/etc/checkgprobot/secrets.env`) 中设置的 env var
2. **GOOGLE_APPLICATION_CREDENTIALS** env var(Google SDK 标准)
3. **CHECKGPROBOT_*** env var(`CHECKGPROBOT_TELEGRAM_BOT_TOKEN` 等)
4. **`secrets.yaml`** 中的字段

## 安全事项

- `/etc/checkgprobot/` 目录 `chmod 700`(只 root 可进)
- `secrets.yaml` / `secrets.env` / `gcp-sa.json` 都 `chmod 600`
- `8765` 端口对外**不开放**,只绑 `127.0.0.1`;公网入口走 nginx:443 + Basic Auth
- **轻量防火墙** 默认开 22/80/443;22 限制到你的 IP
- root SSH 登录建议改成 key-only + 关掉密码登录(`/etc/ssh/sshd_config`)
- Let's Encrypt 证书自动续期(certbot timer)
- 备份数据本地保留 14 天;如需异地,加 OSS sync cron

## 每月费用估算

- 轻量应用服务器 (2核2G 香港区):**约 ¥24-35/月**
- 公网 IP (轻量自带固定 IP):**已包含**
- 数据传输:通常个人项目用不到上限
- **合计:约 ¥24-35/月**

新用户首年通常有折扣券。

## 为什么是香港节点(而不是大陆节点)

| 节点 | 备案 | 上线速度 |
|---|---|---|
| **香港** | ❌ 不用 | 当晚 |
| 北京/上海/广州/深圳 | ✅ 必做(7-20 天) | 一两周后 |
| 新加坡 / 美国 | ❌ 不用 | 当晚,但国内访问慢 |

如果你的域名是 `.cn` / `.com.cn` 等大陆域名,即使在香港节点也建议备案(虽然技术上不强制,但访问稳定性更好)。`.com` / `.net` / `.org` 等国际域名直接用香港节点无影响。