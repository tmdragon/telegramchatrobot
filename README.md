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