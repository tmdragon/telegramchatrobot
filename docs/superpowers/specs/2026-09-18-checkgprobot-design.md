# 多表格可视化与 Telegram 群播报机器人 — 设计

| 项 | 值 |
|---|---|
| 日期 | 2026-09-18 |
| 状态 | Draft（待用户审阅） |
| 项目名 | checkGPRobot |
| 路径 | `D:\soft\checkGPRobot\.spyproject` |

## 1. 目的与范围

### 1.1 背景

用户管理多个 Google Sheets 中的项目，跟踪项目状态、跨表维护数据、向 Telegram 群同步进度。当前痛点：

- 多个 Sheet 分散，没有统一视图
- 字段编辑需要打开每个表，操作繁琐
- 进度信息需要手动同步到群，缺乏自动化

### 1.2 目标用户与使用场景

- **单用户**、**本机运行**
- Python 作为实现语言
- 浏览器访问 `http://localhost:8765` 查看/编辑
- 同一个 Telegram bot 账号加入多个群，按项目编号分发播报

### 1.3 范围

**做**：
- 接入多个 Google Sheets，统一为内存数据模型
- 提供 Web UI 总览所有项目，支持字段编辑并回写 Sheets
- 项目↔Telegram 群映射管理（CRUD + 测试发送）
- Telegram bot 接收命令查询
- APScheduler 定时拉数据、播报到对应群

**不做**（YAGNI）：
- 多用户登录 / 权限系统
- 公网部署 / HTTPS / OAuth
- 复杂工作流引擎（状态机已够用）
- Webhook 模式（long polling 足够）
- 前端 SPA / 大型前端框架

### 1.4 名词术语

| 术语 | 含义 |
|---|---|
| Spreadsheet | 一个 Google Sheets 文件 |
| Sheet | 一个 Spreadsheet 内的工作表 |
| Project | 业务上的"项目"，跨表可能多次出现，靠"项目编号"识别 |
| Status | 项目当前状态，14 个标准状态之一 |
| Mapping | 项目 ↔ Telegram 群 的对应关系 |
| Snapshot | 一次拉取后的全表数据快照 |

---

## 2. 整体架构

### 2.1 架构图

```
┌──────────── 单一 Python 进程 ────────────┐
│                                          │
│   ┌──────────┐    ┌──────────────┐       │
│   │FastAPI   │    │APScheduler   │       │
│   │(UI + API)│    │(定时触发)     │       │
│   └────┬─────┘    └──────┬───────┘       │
│        │                 │               │
│        ▼                 ▼               │
│   ┌──────────┐    ┌──────────────┐       │
│   │SheetRepo │◄──►│BroadcastSvc  │       │
│   │(数据接入) │    │(组装播报)    │       │
│   └────┬─────┘    └──────┬───────┘       │
│        │                 │               │
│   ┌────┴─────────────────┴────┐          │
│   │   In-Memory Store         │          │
│   │  (统一数据模型 + 缓存)     │          │
│   └────────────┬───────────────┘          │
│                │                          │
│         ┌──────▼──────┐                   │
│         │  SQLite     │ (本地持久化)      │
│         └─────────────┘                   │
└──────────────────────────────────────────┘
              ▲                   ▲
              │                   │
   ┌──────────┴────┐    ┌─────────┴────────┐
   │ Google Sheets │    │ Telegram Bot API │
   │ (gspread)     │    │(long polling)    │
   └───────────────┘    └──────────────────┘
```

### 2.2 模块清单

| 模块 | 职责 | 依赖 |
|---|---|---|
| `models.status` | 状态枚举、别名表、状态机合法性校验 | — |
| `models.project` | `Project` / `Field` / `SheetView` / `Mapping` 数据类 | models.status |
| `sheets.repo` | 认证 Google Sheets、读表、识别列 | gspread, google-auth |
| `sheets.parser` | 列识别、状态别名规范化 | models.status |
| `sheets.mapping_repo` | 映射表读写 | gspread |
| `bot.service` | python-telegram-bot 长连接 + 命令处理 | python-telegram-bot |
| `bot.broadcast` | 文案渲染、群发逻辑 | models.project, sheets.repo, bot.service |
| `bot.templates` | 文案模板函数 | — |
| `scheduler.jobs` | APScheduler 任务定义 | bot.broadcast |
| `web.app` | FastAPI 应用入口 | 全部上层 |
| `web.routes` | 路由与 JSON API | web.app, sheets.*, models.* |
| `web.templates` | Jinja2 模板 | — |
| `store.db` | SQLite 封装 | sqlite3 |
| `config` | 加载所有 YAML 配置 | — |

### 2.3 数据流

**读路径**：
1. UI 启动 / 用户手动刷新 / 定时触发 → `SheetRepo.fetch_all()`
2. 解析为 `Project` / `SheetView` 列表，写入内存 Store
3. UI 通过 JSON API 或模板渲染显示
4. SQLite 同步快照

**写路径**：
1. UI 编辑字段 → `PUT /api/projects/{id}/fields/{field_id}`
2. `SheetRepo.update_cell()` 写回 Sheets
3. 重读该单元格确认
4. 更新内存 Store，UI 自动刷新

**播报路径**：
1. APScheduler 触发 `broadcast_job()`
2. 读取 `MappingRepo`（哪些项目要播、播到哪个群）
3. 健康检查（Sheets 可读吗？）
4. 对每个 enabled 映射：拉状态 → 计算停留时长 → 检查阈值 → 渲染文案 → Bot 发送
5. 更新 SQLite 播报历史

---

## 3. 数据模型与状态机

### 3.1 统一数据模型

```python
from dataclasses import dataclass
from typing import Any, Optional
from datetime import datetime

@dataclass
class Field:
    name: str                    # 列名原文（"进度"/"完成率" 等）
    value: Any                   # 当前值
    column_index: int            # 在原 sheet 中的列号（用于回写）
    row_index: int               # 在原 sheet 中的行号
    recognized_as: Optional[str] # 若被识别为"已知字段"，记录是哪个（"project_id"/"status"）

@dataclass
class SheetView:
    spreadsheet_id: str
    sheet_name: str
    fields: list[Field]
    fetched_at: datetime

@dataclass
class Project:
    project_id: str                              # 项目编号
    project_name: Optional[str]                  # 项目名（按列名识别，可选）
    status: Optional["StatusCode"]               # 当前状态
    status_changed_at: Optional[datetime]        # 当前状态起始时间
    status_history: list[tuple["StatusCode", datetime]]  # 最近 N 次流转
    sheets: list[SheetView]                      # 出现的 sheet（多张表时多个）

@dataclass
class Mapping:
    project_id: str
    chat_id: str
    note: str
    enabled: bool
    last_broadcast_at: Optional[datetime]
    last_broadcast_status: Optional[str]  # "ok" / "failed"
    last_error: Optional[str]
```

### 3.2 状态枚举（含别名表）

枚举代码同时作为别名（用户表里可直接写 `MAKING`、`SUBMITTING` 等）：

| Code | 标准显示名 | 别名（大小写不敏感） | 颜色 | 阶段 |
|---|---|---|---|---|
| `ORDERED` | 对方下单 | ORDERED, 下单, 已下单, 待开始, 已下单待制作 | 🔵 | 制作期 |
| `MAKING` | 我方制作中 | MAKING, 制作中, 生产中, 制作 | 🔵 | 制作期 |
| `CLIENT_REVIEW` | 对方验收中 | CLIENT_REVIEW, 验收中, 客户验收, 客户审核 | 🟣 | 验收期 |
| `REWORK` | 返工中 | REWORK, 返工, 修改中, 调整中 | 🟣 | 验收期 |
| `WAITING_AAB` | 等待AAB包 | WAITING_AAB, 等AAB, AAB包准备中 | 🟠 | 审核期 |
| `WAITING_SUBMIT` | 等待提审 | WAITING_SUBMIT, 等待提审, 待提交 | 🟠 | 审核期 |
| `SUBMITTING` | 提审中 | SUBMITTING, 提审中, 提交中, 提交审核 | 🟠 | 审核期 |
| `FIRST_REVIEW_PASSED` | 一审通过 | FIRST_REVIEW_PASSED, 一审通过, 第一轮通过 | 🟠 | 审核期 |
| `FIRST_REVIEW_REJECTED` | 一审打回 | FIRST_REVIEW_REJECTED, 一审打回, 第一轮未通过 | 🔴 | 异常 |
| `SECOND_REVIEW` | 复审中 | SECOND_REVIEW, 复审中, 最终审核 | 🟠 | 审核期 |
| `REMAKING` | 我方重做中 | REMAKING, 重做中, 重新制作, 修复中 | 🟣 | 验收期 |
| `PUBLISHED` | 已发布 | PUBLISHED, 已发布, 上线了, 上架 | 🟢 | 收尾期 |
| `PAID` | 对方已回款 | PAID, 已回款, 已收款, 已结款 | 🟢 | 收尾期（终） |
| `UNPAID` | 对方未回款 | UNPAID, 未回款, 未收款, 待回款 | 🔴 | 异常 |

> PAID ↔ UNPAID 双向流转：发布后客户可后续回款，状态机允许 PAID → UNPAID → PAID。

### 3.3 状态机转换图

```
                          ┌─────────┐
                          │ 对方下单 │ ORDERED
                          └────┬────┘
                               ▼
                          ┌─────────┐
                          │我方制作中│ MAKING
                          └────┬────┘
                               │
                               ▼
                          ┌─────────┐
                          │ 对方验收中│ CLIENT_REVIEW ◄──────────────────────┐
                          └─┬─────┬─┘                                       │
                       不通过  │   通过                                      │
                  ┌──────────┐│                                              │
                  ▼         ││                                              │
              ┌────────┐    ││                                              │
              │ 返工中  │────┘│                                              │
              │ REWORK │     │                                              │
              └────┬───┘     │                                              │
                   └─────────┘  (返工完→回到 CLIENT_REVIEW)                  │
                              ▼                                              │
                  ┌────────────────────┐                                  │
                  │ 等待AAB包→等提审→提审中│                                  │
                  └────────┬────────────┘                                  │
                           ▼                                               │
                  ┌────────────────┐                                       │
                  │ 一审通过/打回    │                                       │
                  └─┬────────────┬──┘                                       │
              一审打回│ │一审通过                                  │
                    ▼ ▼                                            │
              ┌──────────┐ ┌─────────┐                                │
              │ 重新提审  │ │ 复审中  │                                │
              │(回到 SUB- │ │SECOND_  │                                │
              │ MITTING)  │ │ REVIEW  │                                │
              └──────────┘ └─┬─────┬─┘                                │
                              │     │                                    │
                              │     │                                    │
                              ▼     ▼                                    │
                       ┌────────┐ ┌──────────┐                          │
                       │ 已发布 │ │我方重做中 │                          │
                       │PUBLISHED│ │REMAKING  │                          │
                       └──┬───┘ └────┬─────┘                          │
                          ▼         ▼                                  │
              ┌─────────────┐  ┌────────────┐                          │
              │ 对方已回款   │  │我方制作中   │ ────────────────────────┘
              │   PAID      │  │  MAKING    │
              └─────────────┘  └────────────┘
                         ▲
                         │  (回款流转)
                  ┌─────────────┐
                  │ 对方未回款   │
                  │  UNPAID    │ ─── (对方付款了) ──► PAID
                  └─────────────┘
```

**合法转换清单**（`StateMachine.is_legal(from, to)` 实现）：

```python
LEGAL_TRANSITIONS = {
    ORDERED:              {MAKING},
    MAKING:               {CLIENT_REVIEW},
    CLIENT_REVIEW:        {REWORK, WAITING_AAB},           # 不通过→返工；通过→等AAB
    REWORK:               {CLIENT_REVIEW},                 # 返工完→回到验收
    WAITING_AAB:          {WAITING_SUBMIT},
    WAITING_SUBMIT:       {SUBMITTING},
    SUBMITTING:           {FIRST_REVIEW_PASSED, FIRST_REVIEW_REJECTED},
    FIRST_REVIEW_PASSED:  {SECOND_REVIEW},
    FIRST_REVIEW_REJECTED:{SUBMITTING},                    # 重新提审
    SECOND_REVIEW:        {PUBLISHED, REMAKING},
    REMAKING:             {MAKING},                        # 重做后回到制作
    PUBLISHED:            {PAID, UNPAID},
    PAID:                 {UNPAID},                        # 回款可逆转（撤销等）
    UNPAID:               {PAID},
}
```

### 3.4 列识别规则

**已知字段**及其候选列名（第一个非空匹配生效）：

| 已知字段 | 候选列名（模糊匹配，子串即可） |
|---|---|
| `project_id`（项目编号） | "项目编号"、"编号"、"ID"、"Project ID"、"项目 ID" |
| `status`（状态） | "状态"、"当前状态"、"项目状态"、"Status" |
| `project_name`（项目名，可选） | "项目名"、"项目名称"、"Name" |

**识别流程**：
1. 读 sheet 表头行
2. 对每个已知字段，遍历候选列名找匹配列（中文 + 英文双向）
3. 遍历每行，对匹配列取值 → 规范化

**状态识别**：`StatusParser.normalize(value)` 接受任意文本，遍历别名表（含大小写不敏感、空格忽略），命中返回 `StatusCode`，未命中返回 `None`（标为"未知状态"，UI 显示原值）。

---

## 4. 项目 ↔ Telegram 群 映射

### 4.1 映射表结构

存于 Google Sheets（独立 spreadsheet，便于跨设备手动编辑）：

| 项目编号 | 群 chat_id | 备注 | 是否启用 | 上次播报时间 |
|---|---|---|---|---|
| PRJ-001 | -1001234567890 | 一群 | ✅ | 2026-09-18 21:00 |

### 4.2 映射读写流程

- UI 启动时 `MappingRepo.load_all()` 拉映射 → 写入内存 → SQLite 快照
- UI 编辑映射 → `MappingRepo.upsert(mapping)` 写 Sheets → 更新内存 + SQLite
- 删除走软删除（`enabled=false`），保留历史
- 测试发送：UI 点 `📨 测试发送` → 直接调 `BotService.send(chat_id, "test")`，不更新"上次播报时间"

---

## 5. 可视化 UI

### 5.1 三页布局

| 路径 | 页面 |
|---|---|
| `/` | 项目总览（所有项目 + 当前状态 + 在当前状态停留时长） |
| `/project/{project_id}` | 项目详情（该项目在所有 sheet 中的全部字段） |
| `/mappings` | 映射管理（CRUD + 测试发送 + 获取 chat_id 助手） |

技术：Jinja2 模板 + 原生 JS（无 SPA），单页面应用不强求。FastAPI 端口 8765，绑定 `127.0.0.1`。

### 5.2 项目总览（`/`）

```
┌──────────────────────────────────────────────────────────────────────┐
│ 🟢 上次刷新 2 分钟前 | [🔄 手动刷新] [⏸ 自动刷新:开] [⚠ 0 错误]      │
├──────────────────────────────────────────────────────────────────────┤
│ 项目管理 │
├──────────────┬──────────┬───────────────────┬────────────────────────┤
│ 项目编号      │ 项目名 │ 当前状态            │ 在当前状态停留         │
├──────────────┼──────────┼───────────────────┼────────────────────────┤
│ PRJ-001 🔵  │ 项目一    │ 🟣 对方验收中     │ 2 天 3 小时  [查看]    │
│ PRJ-002 🟡  │ 项目二    │ 🟠复审中         │ 18 天 ⚠超过阈值  [查看]│
│ PRJ-003 ⚪  │ 项目三    │ ⚪ 未知          │ —        [查看]        │
└──────────────┴──────────┴───────────────────┴────────────────────────┘
```

### 5.3 项目详情（`/project/{project_id}`）

每个 sheet 一张表，列出所有字段（已识别 + 未识别）：

- **已知字段（🔒 不可改）**：项目编号（在子表中）
- **可编辑字段（✏️）**：点击变 input + ✅❌ 按钮
- **乐观更新**：保存立即更新 UI；失败回滚 + 错误提示

页面顶部显示"总进度"区：当前状态徽章 + 停留时长 + 最近一次状态变更。

### 5.4 映射管理（`/mappings`）

表格 + 新增/编辑模态框 + 删除二次确认 + `📨 测试发送` 按钮 + "本群 chat_id: `xxx`" 显示助手。

### 5.5 错误与状态展示

- 顶部状态栏：拉取中转圈 + "正在刷新…"；失败红色 banner + 重试按钮
- 单元格保存失败：行变红 + 错误提示，**不丢失原始值**
- 表全部读不到：项目总览显示空表 + "⚠ 无法连接 Google Sheets，检查凭证"

---

## 6. Telegram Bot 与定时播报

### 6.1 Bot 账号与连接

- 用户在 @BotFather 创建 bot，拿到 token → 存 `config/secrets.yaml`
- 启动时调 `getMe` 验证 token
- **long polling** 模式（webhook 需要公网域名）

### 6.2 命令处理

| 命令 | 行为 | 权限 |
|---|---|---|
| `/status PRJ-001` | 回复该项目当前状态 + 停留时长 | 所有 |
| `/projects` | 列出所有项目当前状态 | 所有 |
| `/help` | 显示帮助 | 所有 |
| `/force_broadcast` | 立即触发全员播报 | 仅管理员 |
| `/reload` | 重读所有配置 | 仅管理员 |
| `/dryrun` | 渲染文案但不发送，预览 | 仅管理员 |

管理员判定：`message.from_user.id == admin_chat_id`

普通消息 + @bot：bot 回复"我只在被 @ 或收到命令时回复"。

### 6.3 调度策略

APScheduler cron，默认每天 **09:00 和 18:00** 各一次（工作日）。

配置项 `config/scheduler.yaml`：

```yaml
broadcast:
  times: ["09:00", "18:00"]
  weekdays_only: true
  skip_if_no_change: true
  per_status_thresholds:
    MAKING: 14
    CLIENT_REVIEW: 7
    UNPAID: 30
```

**单次执行流程**：
1. 读 `MappingRepo`
2. 健康检查（Sheet 可读？）
3. 对每个 enabled 映射：
   - 拉状态、停留时长、最近变更
   - 是否超阈值 → 标记 ⚠
   - `skip_if_no_change` 且状态无变化 → 跳过。**"状态无变化"判定**：当前 `(status_code, status_changed_at)` 与 SQLite `broadcast_log` 中该 `(project_id, chat_id)` 最近一条成功记录完全相同
   - 渲染文案 → `BotService.send()`
   - 失败重试 3 次（指数退避）
   - 全部失败 → 标记映射"❌ 无法发送"
4. 更新 SQLite 播报历史

### 6.4 播报文案模板

普通播报：

```
📊 *PRJ-001 项目一*
▸ 当前状态：🟣 对方验收中（已停留 2 天 3 小时）
▸ 最近流转：09-16 18:00 由 `我方制作中` → `对方验收中`
▸ 责任人：张三（来自表"项目主表"）

— 09-18 21:00 自动播报
```

异常播报（含 ⚠ 阈值警告）：

```
📊 *PRJ-002 项目二*
▸ 当前状态：🟠复审中（已停留 18 天）⚠ 超过阈值▸ 最近流转：08-30 14:20 由 `一审通过` → `复审中`
▸ 责任人：李四

— 09-18 21:00 自动播报
```

模板函数在 `bot/templates.py`，修改后重启即生效。

### 6.5 错误处理与管理员告警

| 场景 | 处理 |
|---|---|
| Telegram API 失败 | 3 次指数退避重试，最终失败标记映射"❌ 无法发送" |
| 群 chat_id 错误/被踢 | 标记"❌ 无法发送"，UI 标红 |
| Google Sheets 拉取失败 | **跳过整个播报**，避免发空消息 |
| 映射表读不到 | 同上 |
| Bot token 错误 | 启动时校验，启动失败带清晰错误 |
| 单项目拉数据失败 | 该项目跳过，其他项目照常，错误汇总到管理员 |

**管理员告警**：bot 私聊 `admin_chat_id`，例：`⚠ 09-18 21:00 播报部分失败：5 个项目跳过，原因...`

---

## 7. 持久化（SQLite）

文件路径：`data/checkgprobot.db`

### 7.1 表结构

```sql
CREATE TABLE sheet_snapshots (
  spreadsheet_id  TEXT,
  sheet_name      TEXT,
  fetched_at      TIMESTAMP,
  rows_json       TEXT,
  parse_errors    TEXT,
  PRIMARY KEY (spreadsheet_id, sheet_name)
);

CREATE TABLE mapping_snapshot (
  project_id              TEXT PRIMARY KEY,
  chat_id                 TEXT,
  note                    TEXT,
  enabled                 BOOLEAN,
  last_broadcast_at       TIMESTAMP,
  last_broadcast_status   TEXT,
  last_error              TEXT
);

CREATE TABLE broadcast_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id      TEXT,
  chat_id         TEXT,
  status_code     TEXT,
  message_text    TEXT,
  sent_at         TIMESTAMP,
  success         BOOLEAN,
  error           TEXT
);

CREATE TABLE status_history (
  project_id      TEXT,
  status_code     TEXT,
  detected_at     TIMESTAMP,
  PRIMARY KEY (project_id, status_code, detected_at)
);
```

### 7.2 缓存策略

- UI 启动**先读快照**（秒开），后台异步刷新
- 拉表成功立即覆盖 `sheet_snapshots`
- Sheet 拉失败时 UI 显示"上次成功时间" + 错误，不空白

---

## 8. 配置管理

### 8.1 配置文件清单

```
config/
├── secrets.yaml.example     # 模板（git 跟踪）
├── secrets.yaml             # 实际配置（.gitignore）
├── sheets.yaml              # 列出接入的 spreadsheets
└── scheduler.yaml           # 调度策略
```

### 8.2 secrets.yaml

```yaml
google_service_account_json: "data/credentials/gcp-sa.json"
telegram_bot_token: "123456:ABC..."
admin_chat_id: "123456789"
ui_port: 8765
ui_bind: "127.0.0.1"
```

### 8.3 sheets.yaml

```yaml
spreadsheets:
  - id: "1AbC...xyz"
    name: "项目主表"
    role: "master"
  - id: "2DeF...uvw"
    name: "财务子表"
    role: "detail"
```

### 8.4 安全

- `secrets.yaml` 与 `data/credentials/` 加入 `.gitignore`
- 启动时校验 secrets（token 调 `getMe`、SA 文件存在）
- 配置加载失败 → 启动失败，提示明确错误

---

## 9. 测试策略

### 9.1 分层

| 层级 | 测试内容 | 方法 |
|---|---|---|
| 单元 | `StatusParser.normalize()` 别名识别 | 输入各种不规范文本 → 期望 `StatusCode` |
| 单元 | `BroadcastSvc.render()` | 输入假 `Project` → 期望文案字符串 |
| 单元 | `StateMachine.is_legal()` | 给定 from/to → 期望 bool |
| 单元 | `MappingRepo` CRUD | 用 fake repo |
| 集成 | `SheetRepo` | fake gspread client |
| 集成 | 端到端播报 | fake Sheets + fake Bot → 跑完整链路 |
| 手动 e2e | UI 编辑回写 | 真实表，点 UI，验证回写 |

### 9.2 覆盖目标

- 状态识别、播报渲染、状态机合法性：**100%** 行覆盖
- UI 层：不强求单测，靠手动 e2e

---

## 10. 部署与运行

### 10.1 目录结构

```
checkGPRobot/             ← 项目根（git 仓库根）
├── .spyproject/          ← Spyder 配置
│   └── docs/superpowers/specs/  ← 本文档
├── src/
│   ├── main.py
│   ├── config.py
│   ├── models/
│   ├── sheets/
│   ├── bot/
│   ├── scheduler/
│   ├── web/
│   └── store/
├── config/
├── data/
│   ├── checkgprobot.db
│   └── credentials/
├── tests/
├── logs/
├── requirements.txt
├── run.py
└── README.md
```

### 10.2 启动

```bash
pip install -r requirements.txt
cp config/secrets.yaml.example config/secrets.yaml  # 填 token
python run.py
```

**启动流程**：
1. 校验 secrets
2. 初始化 SQLite
3. 立刻拉一次所有 sheet（失败记告警，不致命）
4. 启动 FastAPI（绑定 `127.0.0.1:8765`）
5. 启动 BotService long polling
6. 启动 APScheduler
7. 全部健康 → 打印 `✅ Ready` + 各端点

**停止**：`Ctrl+C` 优雅退出（关 polling、关 scheduler、flush SQLite）。

### 10.3 日志与监控

- `logging` 模块 + 控制台 + `logs/app.log`（按天滚动）
- 格式：`时间 | 级别 | 模块 | 消息`
- ERROR 自动通过 bot 私聊管理员

### 10.4 安全

- UI 绑 `127.0.0.1`，外部访问不到
- 管理员指令需校验 `from_user.id == admin_chat_id`
- secrets 与凭证 `.gitignore`

---

## 11. 验收标准

### 11.1 功能验收

- [ ] 启动后能成功认证 Google Sheets，拉取配置的 spreadsheets
- [ ] 浏览器打开 `http://localhost:8765` 看到项目总览
- [ ] 项目总览正确显示每个项目的项目编号、项目名、当前状态徽章、停留时长
- [ ] 点进项目详情，能看到该项目在所有 sheet 中的字段
- [ ] 编辑任意非已知字段并保存，验证 Google Sheets 中对应单元格被修改
- [ ] 已知字段（项目编号）在子表中不可编辑
- [ ] 映射管理页可新增/编辑/删除/测试发送映射
- [ ] 在 Telegram 群中发 `/status PRJ-001`，bot 正确回复
- [ ] 配置的调度时间到达时，所有 enabled 项目对应群收到播报
- [ ] 状态停留超过阈值时，播报含 ⚠ 警告
- [ ] Sheet 拉取失败时，bot 跳过播报并私聊管理员
- [ ] Telegram API 调用失败时，3 次重试后标记映射"❌ 无法发送"

### 11.2 非功能验收

- [ ] UI 启动 < 2 秒（读 SQLite 快照）
- [ ] 一次完整播报（含 10 个项目） < 30 秒
- [ ] 内存占用 < 500 MB
- [ ] 单进程崩溃需手动重启（无守护进程）
- [ ] secrets 文件不进 git

---

## 12. 后续（不在本次实现范围）

- 多用户支持
- Webhook 模式
- HTTPS / 公网部署
- LLM 生成播报文案（润色）
- 飞书/钉钉等其他平台 bot
- 数据导出 / 报表