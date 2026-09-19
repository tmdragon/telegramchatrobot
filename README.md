# checkGPRobot

多 Google Sheets 可视化 + Telegram 群播报机器人（个人用、本机跑）。

## 状态

- [x] **Phase 1**: 数据接入层（SheetRepo + 状态机 + 持久化 + main 入口）
- [ ] Phase 2: 可视化 UI
- [ ] Phase 3: Telegram Bot
- [ ] Phase 4: 定时调度与播报

设计文档：[docs/superpowers/specs/2026-09-18-checkgprobot-design.md](docs/superpowers/specs/2026-09-18-checkgprobot-design.md)
实施计划：[docs/superpowers/plans/2026-09-18-checkgprobot-phase1-data-layer.md](docs/superpowers/plans/2026-09-18-checkgprobot-phase1-data-layer.md)

## 安装

```bash
pip install -r requirements.txt
```

## 配置

```bash
cp config/secrets.yaml.example config/secrets.yaml
cp config/sheets.yaml.example config/sheets.yaml
# 编辑两个文件填入实际值
```

`secrets.yaml` 需要：
- Google 服务账号 JSON 路径（`data/credentials/gcp-sa.json`）
- Telegram bot token（Phase 3 才需要）
- 管理员 Telegram user_id（Phase 3 才需要）

`sheets.yaml` 列出所有要接入的 spreadsheets。

## 运行（Phase 1）

```bash
python run.py --secrets config/secrets.yaml --sheets config/sheets.yaml
```

应看到：

```
[config] N spreadsheets configured
[store] SQLite initialized at data/checkgprobot.db
[data] Loaded M projects
  • PRJ-001 项目一 — MAKING
  ...
[mapping] Loaded K mappings
```

## 运行（Phase 2）

Phase 1 完成后，再执行一次 `python run.py` —— 同一个入口会顺带启动 FastAPI：

```bash
python run.py --secrets config/secrets.yaml --sheets config/sheets.yaml
```

应看到：

```
[config] N spreadsheets configured
[store] SQLite initialized at data/checkgprobot.db
[data] Loaded M projects
  • PRJ-001 项目一 — MAKING
  ...
[mapping] Loaded K mappings
[ui] Listening on http://127.0.0.1:8765
```

浏览器打开 `http://127.0.0.1:8765` 可访问：

| 路径 | 页面 |
|---|---|
| `/` | 项目总览（所有项目 + 当前状态 + 在当前状态停留时长） |
| `/project/{project_id}` | 项目详情（所有 sheet 字段 + 内联编辑） |
| `/mappings` | 项目 ↔ Telegram 群 映射管理（CRUD） |
| `/health` | 健康检查 JSON |

JSON API：`/api/projects`、`/api/projects/{id}`、`/api/projects/{id}/fields/{field_id}`（PUT）、`/api/refresh`（POST）、`/api/mappings`（GET/POST/PUT/DELETE）。

停止：`Ctrl+C` 优雅退出。

**注意**：服务绑定 `127.0.0.1:8765`，外部网络访问不到（spec §10.4）。

## Phase 3 — Telegram Bot & 定时播报

### 1. 创建 Telegram Bot

1. 跟 [@BotFather](https://t.me/BotFather) 对话：`/newbot`
2. 拿到 token → 填到 `config/secrets.yaml` 的 `telegram_bot_token`
3. 把 admin 账号发给 bot，启动后 `/help` 第一行会回显你的 chat_id → 填到 `admin_chat_id`
4. 把 bot 邀请进目标群（用于群播报）

### 2. 复制调度配置模板

```bash
cp config/scheduler.yaml.example config/scheduler.yaml
# 按需改 times / weekdays_only / per_status_thresholds
```

### 3. 启动

```bash
python run.py --secrets config/secrets.yaml --sheets config/sheets.yaml
# 看到 [bot] token=xxx... admin=xxx
# 看到 [scheduler] 2 cron jobs, weekdays_only=True
# 浏览器打开 http://127.0.0.1:8765
```

### 4. 测试发送

UI 项目映射管理页 → 选中 mapping → 「测试发送」按钮（Phase 3 已激活）。
后端：`POST /api/mappings/{project_id}/test-send` body `{"chat_id": "可选 override"}`。

### 5. Bot 命令

| 命令 | 权限 |
|---|---|
| `/status PRJ-001` | 所有人 |
| `/projects` | 所有人 |
| `/help` | 所有人 |
| `/force_broadcast` | 仅 admin |
| `/reload` | 仅 admin |
| `/dryrun` | 仅 admin |

### 6. 播报逻辑

- 默认 09:00 / 18:00（UTC 触发；本地时区取决于部署）；`weekdays_only=true` 跳过周末
- 状态无变化 → 跳过（spec §6.3 skip_if_no_change）
- 超过 per_status_thresholds 天数 → 文案带 ⚠
- Telegram API 失败 → 1s/2s/4s 指数退避重试；最终失败标记 mapping `❌ 无法发送`，管理员私聊告警

### 7. 依赖

新增（已加入 requirements.txt）：
- `python-telegram-bot[asyncio]>=20.7`
- `APScheduler>=3.10`
- `pytest-asyncio>=1.0`

## 测试

```bash
python -m pytest -v
```

## 目录结构

```
src/
├── main.py              # 入口
├── config.py            # YAML 配置加载
├── models/
│   ├── status.py        # 状态枚举 + 别名 + 状态机
│   └── project.py       # 业务数据模型
├── sheets/
│   ├── auth.py          # Google 认证
│   ├── parser.py        # 列识别 + 字段解析
│   ├── repo.py          # SheetRepo 读写
│   └── mapping_repo.py  # 映射表 CRUD
└── store/
    └── db.py            # SQLite 封装
config/                  # 配置（secrets.yaml 不进 git）
data/                    # 运行时数据（不进 git）
tests/                   # 测试
```