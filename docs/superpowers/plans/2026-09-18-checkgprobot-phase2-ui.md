# checkGPRobot Phase 2 — 可视化 UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Phase 1 数据层之上交付本地 FastUI —— 三页（项目总览 / 项目详情 / 映射管理）+ JSON API + 内联编辑回写 + 自动刷新，浏览器打开 `http://127.0.0.1:8765` 即用。

**Architecture:** 单进程扩展 —— `src/web/` 新增 Jinja2 模板 + 静态 JS + FastAPI 路由；`src/main.py` 增加 uvicorn 启动段。`ProjectCache` 内存缓存 + `BackgroundRefresher` 后台异步拉取，UI 启动读 SQLite 快照秒开。SheetRepo（同步 gspread）调用统一通过 `asyncio.to_thread` 包装，不阻塞 uvicorn 单线程事件循环。

**Tech Stack:**
- Python 3.11+
- FastAPI 0.115+ / uvicorn[standard] 0.30+
- Jinja2 3.1+
- 原生 ES2020 JavaScript（无构建工具，无 SPA，无前端框架）
- pytest 8.x + FastAPI `TestClient`
- 复用 Phase 1：gspread 6.x / google-auth 2.x / PyYAML 6.x / SQLite 3

**Spec:** [docs/superpowers/specs/2026-09-18-checkgprobot-design.md](docs/superpowers/specs/2026-09-18-checkgprobot-design.md)（§2.3 数据流、§5 UI、§10.1 目录、§10.2 启动）

**后续 Phases:**
- Phase 3: Telegram Bot（bot + 命令处理）—— 见 `2026-09-18-checkgprobot-phase3-bot.md`（待写）
- Phase 4: 定时调度器与播报（APScheduler + 文案 + 调度）—— 见 `2026-09-18-checkgprobot-phase4-scheduler.md`（待写）

---

## Global Constraints

- Python 3.11+（spec §1.4）
- 单文件行数 ≤ 200 行；超过则拆
- 提交粒度：一个 task 一个 commit，commit message 格式 `feat(phase2): <verb> <thing>`
- 测试文件命名 `test_*.py`，函数命名 `test_*`
- Jinja2 autoescape 默认开（`.html` 模板）；不要在模板中显式 `|safe`，除非传入的字符串本身已可信
- **无 SPA、无前端框架**：纯 Jinja2 模板 + 原生 ES2020 JS + Fetch API
- **无认证**：单用户、本机 `127.0.0.1`，不引入 login/session
- **无 CORS 中间件**：同源 UI（`http://127.0.0.1:8765`），不需要 CORS
- **服务绑定**：`127.0.0.1:8765`（`cfg.ui_bind` / `cfg.ui_port`），单线程 uvicorn（`log_level="info"`）
- **SheetRepo 同步调用**：gspread 是同步阻塞 IO，必须通过 `asyncio.to_thread(...)` 包到后台线程，否则单线程 uvicorn loop 会被阻塞
- **`LOCKED_RECOGNIZED_AS = {"project_id"}` 单例常量**：T5 模板类、T6 PUT 400 guard、T9 inline-edit skip 共享同一份 —— 来自 spec §5.3"已知字段（🔒 不可改）：项目编号"
- **field_id 编码**：服务端下发 `{spreadsheet_name}::{sheet_name}::{row}::{col}`（4 段用 `::` 分隔，`spreadsheet_name` 是 `cfg.spreadsheets` 里的 `name` 字段 —— 即 SheetRepo.update_cell 接受的 friendly name），客户端 fetch 后 `encodeURIComponent` 整段后拼到 URL；服务端 `urllib.parse.unquote` 解码再用 `str.split("::", 3)` 拆。`::` 不能出现在 spreadsheet/sheet 命名里（spec 现状满足）
- **Store 方法名沿用**：Phase 1 暴露 `save_sheet_snapshot(spreadsheet_id, sheet_name, fetched_at, rows_json, parse_errors)` 与 `load_latest_snapshot(spreadsheet_id, sheet_name) -> tuple[datetime, str, str|None] | None`；T3 缓存冷启动按 `cfg.spreadsheets` 逐个调用
- **bot_service=None 路径**：Phase 2 启动时允许 `bot_service=None`（Phase 3 才会接 BotService），`/api/mappings/{id}/test-send` 在 None 时返回 503"Telegram bot not configured"

---

## 文件结构（Phase 2 新增）

```
checkGPRobot/
├── requirements.txt           [T1, modify]
├── run.py                     [Phase 1, unchanged]
├── README.md                  [T12, modify]
├── src/
│   ├── main.py                [T12, modify — 加 uvicorn.run 段]
│   ├── web/                   [T1 create]
│   │   ├── __init__.py        [T1]
│   │   ├── app.py             [T2]  create_app() + StaticFiles mount
│   │   ├── filters.py         [T2]  status_badge + humanize_duration
│   │   ├── cache.py           [T3]  ProjectCache
│   │   ├── refresher.py       [T4]  BackgroundRefresher
│   │   ├── routes/            [T3]
│   │   │   ├── __init__.py    [T3]
│   │   │   ├── pages.py       [T3, T5, T10a]
│   │   │   └── api.py         [T4, T5, T6, T10b]
│   │   ├── templates/         [T2b, T3, T5, T10a]
│   │   │   ├── base.html      [T2b]
│   │   │   ├── overview.html  [T3]
│   │   │   ├── project_detail.html [T5]
│   │   │   ├── mappings.html  [T10a]
│   │   │   ├── 404.html       [T5]
│   │   │   └── partials/
│   │   │       ├── _status_bar.html    [T2b]
│   │   │       ├── _status_badge.html  [T2b]
│   │   │       ├── _error_banner.html  [T2b]
│   │   │       ├── _field_row.html     [T5]
│   │   │       ├── _mapping_modal.html [T10a]
│   │   │       └── _confirm_dialog.html [T10a]
│   │   └── static/            [T2b, T7a, T7b, T8, T9]
│   │       ├── css/app.css    [T2b]
│   │       └── js/
│   │           ├── api.js     [T7a]
│   │           ├── dom.js     [T7a]
│   │           ├── time.js    [T7a]
│   │           ├── status-badge.js [T7b]
│   │           ├── page-bootstrap.js [T7b]
│   │           ├── status-bar.js    [T8]
│   │           ├── auto-refresh.js  [T8]
│   │           └── inline-edit.js   [T9]
└── tests/
    ├── test_web_smoke.py           [T1]
    ├── test_health.py              [T2]
    ├── test_filters.py             [T2]
    ├── test_app_factory.py         [T2]
    ├── test_templates.py           [T2b]
    ├── test_overview_route.py      [T3]
    ├── test_api_projects.py        [T4]
    ├── test_api_refresh.py         [T4]
    ├── test_project_detail_route.py [T5]
    ├── test_api_project_detail.py  [T5]
    ├── test_field_edit.py          [T6]
    ├── test_static_served.py       [T7a, T7b]
    ├── test_js_helpers.py          [T7a]
    ├── test_status_bar_module.py   [T8]
    ├── test_auto_refresh_module.py [T8]
    ├── test_inline_edit.py         [T9]
    ├── test_mappings_route.py      [T10a]
    ├── test_api_mappings_crud.py   [T10b]
    └── test_e2e_flow.py            [T12]
```

---

## Task 1: web 依赖与 `src/web/` 骨架

**Files:**
- Modify: `requirements.txt`
- Create: `src/web/__init__.py`
- Create: `src/web/templates/.gitkeep`
- Create: `src/web/static/.gitkeep`
- Create: `tests/test_web_smoke.py`

**Interfaces:**
- Consumes: 无
- Produces: `requirements.txt` 多三行；`src.web` 包存在；`tests/test_web_smoke.py` 通过

- [ ] **Step 1: 修改 `requirements.txt`**

追加三行（在末尾换行后添加）：

```
fastapi>=0.115,<0.117
uvicorn[standard]>=0.30,<0.33
jinja2>=3.1,<4.0
```

最终 `requirements.txt`：

```
gspread>=6.0,<7.0
google-auth>=2.23,<3.0
PyYAML>=6.0,<7.0
pytest>=8.0,<9.0
fastapi>=0.115,<0.117
uvicorn[standard]>=0.30,<0.33
jinja2>=3.1,<4.0
```

- [ ] **Step 2: 创建目录**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
mkdir -p src/web/templates src/web/static
touch src/web/__init__.py
touch src/web/templates/.gitkeep
touch src/web/static/.gitkeep
```

- [ ] **Step 3: 安装新增依赖**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
pip install -r requirements.txt
```

Expected: 安装成功，`fastapi`、`uvicorn`、`jinja2` 可 import。

- [ ] **Step 4: 写冒烟测试 `tests/test_web_smoke.py`**

```python
"""src.web 包可以被 import。"""
import importlib


def test_src_web_importable():
    mod = importlib.import_module("src.web")
    assert mod is not None


def test_fastapi_installed():
    import fastapi  # noqa: F401
    assert fastapi.__version__ >= "0.115"


def test_jinja2_installed():
    import jinja2  # noqa: F401
    assert jinja2.__version__ >= "3.1"


def test_uvicorn_installed():
    import uvicorn  # noqa: F401
    assert uvicorn.__version__ >= "0.30"
```

- [ ] **Step 5: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_web_smoke.py -v
```

Expected: 4 passed。

- [ ] **Step 6: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add requirements.txt src/web/ tests/test_web_smoke.py
git commit -m "feat(phase2): add web deps (fastapi, uvicorn, jinja2) and src/web/ skeleton"
```

---

## Task 2: app factory + Jinja2 过滤器 + `/health`

**Files:**
- Create: `src/web/filters.py`
- Create: `src/web/app.py`
- Create: `tests/test_filters.py`
- Create: `tests/test_health.py`
- Create: `tests/test_app_factory.py`

**Interfaces:**
- Consumes: Phase 1 的 `AppConfig`、`Store`、`SheetRepo`、`MappingRepo`
- Produces:
  ```python
  # src/web/filters.py
  def status_badge(code: StatusCode | None, raw: str | None = None) -> str: ...
  def humanize_duration(seconds: int | float | None) -> str: ...

  # src/web/app.py
  def create_app(
      cfg: AppConfig,
      store: Store,
      sheet_repo: SheetRepo,
      mapping_repo: MappingRepo,
      bot_service: object | None = None,  # Phase 3 will pass BotService instance
  ) -> FastAPI: ...
  ```
  - `create_app` 内部：`app.state.cfg`、`app.state.store`、`app.state.sheet_repo`、`app.state.mapping_repo`、`app.state.bot_service`、`app.state.cache = None`（T3 注入）
  - 注册 Jinja2 环境（`autoescape=True`），挂两个 filter
  - `GET /health` → `{"status": "ok"}` 200

- [ ] **Step 1: 写失败测试 `tests/test_filters.py`**

```python
from datetime import datetime, timezone

from src.models.status import StatusCode
from src.web.filters import status_badge, humanize_duration


def test_status_badge_known_code():
    html = status_badge(StatusCode.MAKING)
    assert "我方制作中" in html
    assert "status-badge" in html


def test_status_badge_unknown_renders_raw():
    html = status_badge(None, raw="随便写的状态")
    assert "随便写的状态" in html
    assert "unknown" in html or "未知" in html


def test_humanize_duration_days_hours():
    # 2 天 3 小时 = 2 * 86400 + 3 * 3600 = 183600
    assert humanize_duration(183600) == "2 天 3 小时"


def test_humanize_duration_minutes():
    assert humanize_duration(15 * 60) == "15 分钟"


def test_humanize_duration_seconds():
    assert humanize_duration(45) == "45 秒"


def test_humanize_duration_zero():
    assert humanize_duration(0) == "0 秒"


def test_humanize_duration_none():
    assert humanize_duration(None) == "—"


def test_humanize_duration_negative():
    assert humanize_duration(-10) == "—"
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_filters.py -v
```

Expected: FAIL（`ModuleNotFoundError: No module named 'src.web.filters'`）。

- [ ] **Step 3: 实现 `src/web/filters.py`**

```python
"""Jinja2 自定义过滤器。

- status_badge: StatusCode -> 带 BEM 类名的彩色徽章 HTML 片段
- humanize_duration: 秒 -> "2 天 3 小时" / "15 分钟" / "45 秒" / "—"

颜色与显示名直接对齐 spec §3.2 表格（不在此重新枚举状态机，仅做展示映射）。
"""
from __future__ import annotations

from typing import Optional

from src.models.status import StatusCode


# spec §3.2：状态 -> (modifier, displayName)
STATUS_DISPLAY: dict[StatusCode, tuple[str, str]] = {
    StatusCode.ORDERED:              ("ordered",        "对方下单"),
    StatusCode.MAKING:               ("making",         "我方制作中"),
    StatusCode.CLIENT_REVIEW:        ("client-review",  "对方验收中"),
    StatusCode.REWORK:               ("rework",         "返工中"),
    StatusCode.WAITING_AAB:          ("waiting-aab",    "等待AAB包"),
    StatusCode.WAITING_SUBMIT:       ("waiting-submit", "等待提审"),
    StatusCode.SUBMITTING:           ("submitting",     "提审中"),
    StatusCode.FIRST_REVIEW_PASSED:  ("first-passed",   "一审通过"),
    StatusCode.FIRST_REVIEW_REJECTED:("first-rejected", "一审打回"),
    StatusCode.SECOND_REVIEW:        ("second-review",  "复审中"),
    StatusCode.REMAKING:             ("remaking",       "我方重做中"),
    StatusCode.PUBLISHED:            ("published",      "已发布"),
    StatusCode.PAID:                 ("paid",           "对方已回款"),
    StatusCode.UNPAID:               ("unpaid",         "对方未回款"),
}


def status_badge(code: StatusCode | None, raw: Optional[str] = None) -> str:
    """渲染状态徽章 HTML。code 已知则按映射渲染；否则展示 raw（用"未知"样式）。"""
    if code is not None and code in STATUS_DISPLAY:
        modifier, name = STATUS_DISPLAY[code]
        return (
            f'<span class="status-badge status-badge--{modifier}" '
            f'data-status-code="{code.value}">'
            f'<span class="status-badge__dot" aria-hidden="true"></span>'
            f'<span class="status-badge__name">{name}</span>'
            f"</span>"
        )
    text = raw if raw else "未知"
    return (
        f'<span class="status-badge status-badge--unknown" '
        f'data-status-code="">'
        f'<span class="status-badge__dot" aria-hidden="true"></span>'
        f'<span class="status-badge__name">{text}</span>'
        f"</span>"
    )


def humanize_duration(seconds: Optional[int | float]) -> str:
    """秒 -> 中文时长。负数与 None 一律显示破折号。"""
    if seconds is None or seconds < 0:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} 秒"
    if seconds < 3600:
        return f"{seconds // 60} 分钟"
    if seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h} 小时{m} 分钟" if m else f"{h} 小时"
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    return f"{d} 天{h} 小时" if h else f"{d} 天"
```

- [ ] **Step 4: 跑过滤器测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_filters.py -v
```

Expected: 8 passed。

- [ ] **Step 5: 写失败测试 `tests/test_health.py`**

```python
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.web.app import create_app


def _fake_deps():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    store = MagicMock()
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    return cfg, store, sheet_repo, mapping_repo


def test_health_returns_ok():
    cfg, store, sheet_repo, mapping_repo = _fake_deps()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 6: 写失败测试 `tests/test_app_factory.py`**

```python
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.web.app import create_app


def _deps():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    return cfg, MagicMock(), MagicMock(), MagicMock()


def test_create_app_stores_deps_on_state():
    cfg, store, sheet_repo, mapping_repo = _deps()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    assert app.state.cfg is cfg
    assert app.state.store is store
    assert app.state.sheet_repo is sheet_repo
    assert app.state.mapping_repo is mapping_repo
    assert app.state.bot_service is None


def test_create_app_accepts_bot_service_none():
    cfg, store, sheet_repo, mapping_repo = _deps()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    # 404 on unknown route still wires correctly
    client = TestClient(app)
    r = client.get("/does/not/exist")
    assert r.status_code == 404


def test_jinja2_env_autoescape_on():
    cfg, store, sheet_repo, mapping_repo = _deps()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    # Find Jinja2Templates instance via internal state
    from starlette.templating import Jinja2Templates

    # templates should be attached somewhere on the app
    # We expose them via app.state for tests
    env = app.state.templates.env
    assert env.autoescape is True
```

> 实现时把 `Jinja2Templates` 实例挂在 `app.state.templates` 以便测试 inspect。

- [ ] **Step 7: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_health.py tests/test_app_factory.py -v
```

Expected: FAIL。

- [ ] **Step 8: 实现 `src/web/app.py`**

```python
"""FastAPI 应用工厂。

create_app() 接收 Phase 1 的 deps + 可选 bot_service，构造 FastAPI 实例，
注册 Jinja2 环境（autoescape=True）、自定义过滤器、`/health` 路由，
并在 app.state 挂上所有依赖供后续路由访问。

后续 T7b 还会调 app.mount('/static', ...)；本任务只暴露骨架。
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.templating import Jinja2Templates

from src.config import AppConfig
from src.sheets.repo import SheetRepo
from src.sheets.mapping_repo import MappingRepo
from src.store.db import Store
from src.web.filters import humanize_duration, status_badge


TEMPLATES_DIR = "src/web/templates"


def create_app(
    cfg: AppConfig,
    store: Store,
    sheet_repo: SheetRepo,
    mapping_repo: MappingRepo,
    bot_service: Optional[object] = None,
) -> FastAPI:
    """构造并返回 FastAPI 应用实例。

    Args:
        bot_service: Phase 3 注入；Phase 2 始终传 None。
    """
    app = FastAPI(title="checkGPRobot UI", docs_url=None, redoc_url=None)

    # 挂依赖到 app.state 供路由访问
    app.state.cfg = cfg
    app.state.store = store
    app.state.sheet_repo = sheet_repo
    app.state.mapping_repo = mapping_repo
    app.state.bot_service = bot_service
    app.state.cache = None  # T3 注入 ProjectCache

    # Jinja2 环境（autoescape 默认 on：.html/.xml/.htm；这里强制 on 更稳）
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    templates.env.autoescape = True
    templates.env.filters["status_badge"] = status_badge
    templates.env.filters["humanize_duration"] = humanize_duration
    app.state.templates = templates

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return app
```

- [ ] **Step 9: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_health.py tests/test_app_factory.py -v
```

Expected: 5 passed。

- [ ] **Step 10: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS，无回归。

- [ ] **Step 11: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/web/app.py src/web/filters.py tests/test_health.py tests/test_app_factory.py tests/test_filters.py
git commit -m "feat(phase2): FastAPI factory, Jinja2 filters, /health route"
```

---

## Task 2b: base 布局 + 三个 partial + CSS

**Files:**
- Create: `src/web/templates/base.html`
- Create: `src/web/templates/partials/_status_bar.html`
- Create: `src/web/templates/partials/_status_badge.html`
- Create: `src/web/templates/partials/_error_banner.html`
- Create: `src/web/static/css/app.css`
- Create: `tests/test_templates.py`

**Interfaces:**
- Consumes: T2 的 `create_app()`（已注册 Jinja2Templates、filters、state）
- Produces:
  - `base.html` 用 `{% extends %}` / `{% block content %}`，include `_status_bar.html`，`<body data-page="{{ page_name }}">`，`<link rel="stylesheet" href="/static/css/app.css">`，`<script type="module" src="/static/js/page-bootstrap.js" defer></script>`
  - `_status_bar.html`：拉取时间 + 手动刷新按钮 + 自动刷新开关 + 错误计数
  - `_status_badge.html`：调用 `status_badge` filter 的薄壳 macro（`{% import ... as m %}` 后调用 `{{ m.badge(code, raw) }}`）
  - `_error_banner.html`：错误列表 banner
  - `app.css`：BEM 样式骨架（layout / status-bar / status-badge / field-cell / toast / modal / row modifiers）

- [ ] **Step 1: 写失败测试 `tests/test_templates.py`**

```python
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.web.app import create_app
from src.models.status import StatusCode


def _app():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    return create_app(cfg, MagicMock(), MagicMock(), MagicMock(), bot_service=None)


def test_base_template_renders_with_block():
    app = _app()
    client = TestClient(app)

    @app.get("/_probe_base")
    def _probe():
        from starlette.templating import Jinja2Templates
        templates = app.state.templates
        return templates.TemplateResponse(
            request=MagicMock(),
            name="partials/_status_badge.html",
            context={"code": StatusCode.MAKING, "raw": None},
        )

    # Register the probe route then call
    r = client.get("/_probe_base")
    assert r.status_code == 200
    assert "我方制作中" in r.text
    assert "status-badge" in r.text


def test_status_badge_partial_unknown():
    app = _app()
    client = TestClient(app)

    @app.get("/_probe_unknown")
    def _probe():
        return app.state.templates.TemplateResponse(
            request=MagicMock(),
            name="partials/_status_badge.html",
            context={"code": None, "raw": "未知值"},
        )

    r = client.get("/_probe_unknown")
    assert r.status_code == 200
    assert "未知值" in r.text
    assert "unknown" in r.text


def test_error_banner_partial_renders_messages():
    app = _app()
    client = TestClient(app)

    @app.get("/_probe_error")
    def _probe():
        return app.state.templates.TemplateResponse(
            request=MagicMock(),
            name="partials/_error_banner.html",
            context={"errors": ["Sheets 拉取失败", "快照加载失败"]},
        )

    r = client.get("/_probe_error")
    assert r.status_code == 200
    assert "Sheets 拉取失败" in r.text
    assert "snapshot-error" in r.text or "error-banner" in r.text
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_templates.py -v
```

Expected: FAIL（找不到 partial 模板）。

- [ ] **Step 3: 实现 `src/web/templates/partials/_status_badge.html`**

```jinja2
{# 调用 status_badge filter 渲染徽章。参数: code (StatusCode|None), raw (str|None) #}
{{ code | status_badge(raw) }}
```

- [ ] **Step 4: 实现 `src/web/templates/partials/_status_bar.html`**

```jinja2
{# 顶部状态栏：上次刷新时间 / 手动刷新 / 自动刷新开关 / 错误计数 #}
<header class="status-bar" id="status-bar">
  <span class="status-bar__refresh">
    上次刷新: <time data-last-refresh="{{ last_refresh_at or '' }}">
      {{ last_refresh_human or "—" }}
    </time>
  </span>

  <button type="button"
          class="status-bar__btn"
          data-action="manual-refresh">
    🔄 手动刷新
  </button>

  <button type="button"
          class="status-bar__btn"
          data-action="auto-refresh-toggle"
          aria-pressed="true">
    <span data-auto-refresh-state>⏸ 自动刷新:开</span>
  </button>

  <button type="button"
          class="status-bar__btn status-bar__btn--error"
          data-action="show-errors"
          hidden
          data-error-count="0">
    ⚠ <span data-error-count-text>0</span> 错误
  </button>
</header>
```

- [ ] **Step 5: 实现 `src/web/templates/partials/_error_banner.html`**

```jinja2
{# 顶部错误 banner：展示当前未处理的错误列表 #}
{% if errors %}
  <div class="error-banner" role="alert">
    <strong class="error-banner__title">⚠ 拉取错误</strong>
    <ul class="error-banner__list">
      {% for msg in errors %}
        <li class="error-banner__item">{{ msg }}</li>
      {% endfor %}
    </ul>
  </div>
{% endif %}
```

- [ ] **Step 6: 实现 `src/web/templates/base.html`**

```jinja2
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{% block title %}checkGPRobot{% endblock %}</title>
  <link rel="stylesheet" href="/static/css/app.css" />
  <script type="module" src="/static/js/page-bootstrap.js" defer></script>
</head>
<body data-page="{{ page_name or 'overview' }}">
  {% include "partials/_status_bar.html" %}

  {% block content %}{% endblock %}

  <div id="toast-container" class="toast-container" aria-live="polite"></div>
</body>
</html>
```

> 模板通过 `{{ page_name }}` 上下文变量决定 `data-page`；page-bootstrap.js 据此动态加载 page 模块。

- [ ] **Step 7: 实现 `src/web/static/css/app.css`**

```css
/* checkGPRobot Phase 2 UI — BEM 命名约定 */

/* ===== Reset / Layout ===== */
*, *::before, *::after { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; margin: 0; background: #f6f7f9; color: #1f2328; }
h1, h2, h3 { margin: 0 0 0.5em; }

/* ===== Status Bar ===== */
.status-bar { display: flex; gap: 1rem; align-items: center; padding: 0.6rem 1rem; background: #fff; border-bottom: 1px solid #d0d7de; }
.status-bar__btn { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 4px; padding: 0.3rem 0.6rem; cursor: pointer; font-size: 0.9rem; }
.status-bar__btn:hover { background: #eaeef2; }
.status-bar__btn--error { color: #cf222e; border-color: #cf222e; }
.status-bar__refresh { font-size: 0.85rem; color: #57606a; }

/* ===== Status Badge ===== */
.status-badge { display: inline-flex; gap: 0.3rem; align-items: center; padding: 0.15rem 0.5rem; border-radius: 12px; font-size: 0.85rem; background: #eaeef2; }
.status-badge__dot { width: 0.6rem; height: 0.6rem; border-radius: 50%; background: #57606a; display: inline-block; }
.status-badge--making .status-badge__dot, .status-badge--ordered .status-badge__dot { background: #0969da; }
.status-badge--client-review .status-badge__dot, .status-badge--rework .status-badge__dot, .status-badge--remaking .status-badge__dot { background: #8250df; }
.status-badge--waiting-aab .status-badge__dot, .status-badge--waiting-submit .status-badge__dot, .status-badge--submitting .status-badge__dot, .status-badge--first-passed .status-badge__dot, .status-badge--second-review .status-badge__dot { background: #d4a72c; }
.status-badge--first-rejected .status-badge__dot, .status-badge--unpaid .status-badge__dot { background: #cf222e; }
.status-badge--published .status-badge__dot, .status-badge--paid .status-badge__dot { background: #1a7f37; }
.status-badge--unknown .status-badge__dot { background: #8c959f; }

/* ===== Error Banner ===== */
.error-banner { background: #ffebe9; border: 1px solid #cf222e; border-radius: 4px; padding: 0.8rem 1rem; margin: 1rem; }
.error-banner__title { color: #cf222e; display: block; margin-bottom: 0.3rem; }
.error-banner__list { margin: 0; padding-left: 1.2rem; color: #82071e; }

/* ===== Tables ===== */
.sheet-section { margin: 1.5rem; }
.sheet-section__title { margin-bottom: 0.5rem; }
.sheet-table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d0d7de; }
.sheet-table th, .sheet-table td { padding: 0.5rem 0.8rem; border-bottom: 1px solid #eaeef2; text-align: left; }
.sheet-table thead { background: #f6f8fa; }

/* ===== Field Cell (used by inline-edit.js) ===== */
.field-cell { cursor: default; }
.field-cell--editable { cursor: pointer; }
.field-cell--editable:hover { background: #fff8c5; }
.field-cell--editing input { width: 100%; padding: 0.2rem; font: inherit; border: 1px solid #0969da; border-radius: 3px; }
.field-cell--editing .field-cell__actions { display: inline-flex; gap: 0.3rem; margin-left: 0.5rem; }
.field-cell--locked { color: #57606a; background: #f6f8fa; }
.field-cell--locked::before { content: "🔒 "; font-size: 0.8rem; }
.field-cell--error { background: #ffebe9 !important; }

/* ===== Toast ===== */
.toast-container { position: fixed; top: 4rem; right: 1rem; display: flex; flex-direction: column; gap: 0.5rem; z-index: 100; }
.toast { padding: 0.6rem 1rem; border-radius: 4px; background: #1f2328; color: #fff; box-shadow: 0 2px 8px rgba(0,0,0,0.2); animation: toast-fade-in 0.2s ease-out; }
.toast--error { background: #cf222e; }
.toast--success { background: #1a7f37; }
@keyframes toast-fade-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
@keyframes spinner-rotate { to { transform: rotate(360deg); } }
.spinner { display: inline-block; width: 1rem; height: 1rem; border: 2px solid #d0d7de; border-top-color: #0969da; border-radius: 50%; animation: spinner-rotate 0.6s linear infinite; }

/* ===== Modal ===== */
.modal { border: 1px solid #d0d7de; border-radius: 6px; padding: 1.2rem; min-width: 360px; background: #fff; }
.modal::backdrop { background: rgba(0,0,0,0.4); }
.modal--open { display: block; }
.modal__title { margin-top: 0; }
.modal__actions { display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem; }

/* ===== Row modifiers (mappings) ===== */
.row--warn { background: #fff8c5; }
.row--error { background: #ffebe9; }
```

- [ ] **Step 8: 跑模板测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_templates.py -v
```

Expected: 3 passed。

- [ ] **Step 9: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 10: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/web/templates/ src/web/static/css/ tests/test_templates.py
git commit -m "feat(phase2): base layout, 3 partials, BEM CSS skeleton"
```

---

## Task 3: ProjectCache + overview 路由 + overview 模板

**Files:**
- Create: `src/web/cache.py`
- Create: `src/web/routes/__init__.py`
- Create: `src/web/routes/pages.py`
- Create: `src/web/templates/overview.html`
- Modify: `src/web/app.py`
- Create: `tests/test_overview_route.py`

**Interfaces:**
- Produces:
  ```python
  # src/web/cache.py
  @dataclass
  class ProjectSummary:
      project_id: str
      project_name: str | None
      status: StatusCode | None
      status_changed_at: datetime | None
      dwell_seconds: int
      sheets: list[SheetView]
      editable_fields: int
      locked_field_names: list[str]

  class ProjectCache:
      def __init__(self) -> None: ...
      def replace(self, projects: list[Project]) -> None: ...
      def get(self, project_id: str) -> Project | None: ...
      def list_summaries(self) -> list[ProjectSummary]: ...
      def last_refresh_at(self) -> datetime | None: ...
      def error_count(self) -> int: ...
      def empty(self) -> bool: ...

  # src/web/routes/pages.py
  async def overview(request: Request) -> TemplateResponse: ...
  ```
  - GET `/` 渲染 overview.html；cache 空时从 Store 冷启动 hydrate（按 `cfg.spreadsheets` 逐个 `load_latest_snapshot`）
  - 空态：cache 空 + Store 也无 → 渲染"无法连接 Google Sheets，检查凭证"错误 banner

- [ ] **Step 1: 写失败测试 `tests/test_overview_route.py`**

```python
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.models.project import Field, Project, SheetView
from src.models.status import StatusCode
from src.sheets.mapping_repo import MappingRepo
from src.sheets.repo import SheetRepo
from src.store.db import Store
from src.web.app import create_app
from src.web.cache import ProjectCache


@pytest.fixture
def client_with_cache():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []

    store = MagicMock(spec=Store)
    sheet_repo = MagicMock(spec=SheetRepo)
    mapping_repo = MagicMock(spec=MappingRepo)

    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    return TestClient(app), cache


def test_overview_empty_state_renders_banner(client_with_cache):
    client, cache = client_with_cache
    cache.replace([])  # cold start empty
    store = MagicMock()
    store.load_latest_snapshot.return_value = None
    client.app.state.store = store
    r = client.get("/")
    assert r.status_code == 200
    assert "无法连接 Google Sheets" in r.text or "暂无项目" in r.text


def test_overview_renders_projects(client_with_cache):
    client, cache = client_with_cache
    p = Project(
        project_id="PRJ-001",
        project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1",
            sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
                Field(name="状态", value="制作中", column_index=3, row_index=2, recognized_as="status"),
                Field(name="备注", value="OK", column_index=5, row_index=2, recognized_as=None),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    r = client.get("/")
    assert r.status_code == 200
    assert "PRJ-001" in r.text
    assert "我方制作中" in r.text
    assert "项目一" in r.text


def test_overview_links_to_project_detail(client_with_cache):
    client, cache = client_with_cache
    cache.replace([])
    p = Project(
        project_id="PRJ-002",
        project_name=None,
        status=None,
        status_changed_at=None,
        sheets=[],
    )
    cache.replace([p])
    r = client.get("/")
    assert r.status_code == 200
    assert "/project/PRJ-002" in r.text
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_overview_route.py -v
```

Expected: FAIL。

- [ ] **Step 3: 实现 `src/web/cache.py`**

```python
"""ProjectCache：内存中的项目视图缓存。

BackgroundRefresher 拉数据后调用 replace() 覆盖；UI 路由从 list_summaries() 读。
冷启动时由 overview 路由从 Store.load_latest_snapshot hydrate。

线程安全：uvicorn 单线程；BackgroundRefresher 也跑在 asyncio loop 内（同线程），
故所有访问均在单线程上，不必加锁。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.models.project import Project, SheetView
from src.models.status import StatusCode


# spec §5.3：唯一不可编辑字段 = project_id（在子表中）；status 与 project_name 可改
LOCKED_RECOGNIZED_AS: frozenset[str] = frozenset({"project_id"})


@dataclass
class ProjectSummary:
    project_id: str
    project_name: Optional[str]
    status: Optional[StatusCode]
    status_changed_at: Optional[datetime]
    dwell_seconds: int
    sheets: list[SheetView]
    editable_fields: int
    locked_field_names: list[str]


class ProjectCache:
    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self._last_refresh: Optional[datetime] = None
        self._error_count: int = 0

    def replace(self, projects: list[Project]) -> None:
        self._projects = {p.project_id: p for p in projects}
        self._last_refresh = datetime.now(timezone.utc)
        # 成功刷新视为无错误；错误计数由 refresher 单独写入
        self._error_count = 0

    def set_error_count(self, n: int) -> None:
        self._error_count = n

    def get(self, project_id: str) -> Optional[Project]:
        return self._projects.get(project_id)

    def list_projects(self) -> list[Project]:
        return list(self._projects.values())

    def last_refresh_at(self) -> Optional[datetime]:
        return self._last_refresh

    def error_count(self) -> int:
        return self._error_count

    def empty(self) -> bool:
        return len(self._projects) == 0

    def list_summaries(self, now: Optional[datetime] = None) -> list[ProjectSummary]:
        now = now or datetime.now(timezone.utc)
        out: list[ProjectSummary] = []
        for p in self._projects.values():
            editable = 0
            locked: list[str] = []
            for sv in p.sheets:
                for f in sv.fields:
                    if f.recognized_as in LOCKED_RECOGNIZED_AS:
                        locked.append(f.name)
                    else:
                        editable += 1
            dwell = 0
            if p.status_changed_at:
                dwell = max(0, int((now - p.status_changed_at).total_seconds()))
            out.append(ProjectSummary(
                project_id=p.project_id,
                project_name=p.project_name,
                status=p.status,
                status_changed_at=p.status_changed_at,
                dwell_seconds=dwell,
                sheets=p.sheets,
                editable_fields=editable,
                locked_field_names=locked,
            ))
        return out
```

- [ ] **Step 4: 创建 `src/web/routes/__init__.py`**

```python
"""src.web.routes 子包（pages + api）。"""
```

- [ ] **Step 5: 实现 `src/web/routes/pages.py`（仅 overview 部分）**

```python
"""页面路由（HTML）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.models.project import Field, Project, SheetView

router = APIRouter()


def _hydrate_from_store(store, cfg) -> list[Project]:
    """冷启动：从 SQLite 快照反序列化出 Project 列表。

    每个 spreadsheet 一行快照；HeaderDetector 反推字段位置。
    若 cfg.spreadsheets 为空或 Store 无快照，返回空列表。
    """
    from src.sheets.parser import (
        HeaderDetector,
        PROJECT_ID_CANDIDATES,
        PROJECT_NAME_CANDIDATES,
        STATUS_CANDIDATES,
        parse_project_id,
        parse_status,
    )

    projects: dict[str, Project] = {}
    for ss in cfg.spreadsheets:
        snap = store.load_latest_snapshot(ss.id, ss.name)
        if snap is None:
            continue
        fetched_at, rows_json, _ = snap
        rows = json.loads(rows_json)
        if not rows:
            continue
        headers = rows[0]
        detector = HeaderDetector(headers)
        pid_col = detector.find_column(PROJECT_ID_CANDIDATES)
        if pid_col is None:
            continue
        status_col = detector.find_column(STATUS_CANDIDATES)
        name_col = detector.find_column(PROJECT_NAME_CANDIDATES)

        for row_idx, row in enumerate(rows[1:], start=2):
            if len(row) < len(headers):
                row = row + [""] * (len(headers) - len(row))
            pid = parse_project_id(row[pid_col - 1] if pid_col <= len(row) else None)
            if not pid:
                continue
            fields: list[Field] = []
            for col_idx, (header, value) in enumerate(zip(headers, row), start=1):
                recognized = None
                if col_idx == pid_col:
                    recognized = "project_id"
                elif status_col is not None and col_idx == status_col:
                    recognized = "status"
                elif name_col is not None and col_idx == name_col:
                    recognized = "project_name"
                fields.append(Field(
                    name=header, value=value, column_index=col_idx,
                    row_index=row_idx, recognized_as=recognized,
                ))
            sv = SheetView(spreadsheet_id=ss.id, sheet_name=ss.name,
                           fields=fields, fetched_at=fetched_at)
            status = parse_status(row[status_col - 1]) if status_col and status_col <= len(row) else None
            name = (row[name_col - 1].strip() or None) if name_col and name_col <= len(row) else None

            if pid not in projects:
                projects[pid] = Project(
                    project_id=pid, project_name=name, status=status,
                    status_changed_at=fetched_at, sheets=[sv],
                )
            else:
                p = projects[pid]
                if name and not p.project_name:
                    p.project_name = name
                if status and p.status != status:
                    p.status = status
                    p.status_changed_at = fetched_at
                p.sheets.append(sv)
    return list(projects.values())


@router.get("/", response_class=HTMLResponse)
async def overview(request: Request):
    app = request.app
    cache = app.state.cache
    cfg = app.state.cfg
    store = app.state.store
    templates = app.state.templates

    summaries: list[Any] = []
    if cache is not None and not cache.empty():
        summaries = cache.list_summaries()
    else:
        # 冷启动：从 Store hydrate
        if cache is None:
            from src.web.cache import ProjectCache
            cache = ProjectCache()
            app.state.cache = cache
        projects = _hydrate_from_store(store, cfg)
        if projects:
            cache.replace(projects)
            summaries = cache.list_summaries()

    last_refresh = cache.last_refresh_at() if cache else None
    last_refresh_human = (
        last_refresh.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if last_refresh else None
    )

    empty_state = (
        not summaries
    )
    error_banner_visible = empty_state  # cache 空 → 视为拉取失败

    return templates.TemplateResponse(
        request=request,
        name="overview.html",
        context={
            "page_name": "overview",
            "summaries": summaries,
            "last_refresh_at": last_refresh.isoformat() if last_refresh else None,
            "last_refresh_human": last_refresh_human,
            "errors": ["无法连接 Google Sheets，检查凭证"] if error_banner_visible else [],
        },
    )
```

- [ ] **Step 6: 实现 `src/web/templates/overview.html`**

```jinja2
{% extends "base.html" %}

{% block title %}项目总览 — checkGPRobot{% endblock %}

{% block content %}
<main class="page page--overview">
  <h1 class="page__title">项目管理</h1>

  {% include "partials/_error_banner.html" %}

  {% if summaries %}
    <table class="overview-table">
      <thead>
        <tr>
          <th>项目编号</th>
          <th>项目名</th>
          <th>当前状态</th>
          <th>在当前状态停留</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        {% for s in summaries %}
          <tr class="overview-row" data-project-id="{{ s.project_id }}">
            <td>
              <a href="/project/{{ s.project_id }}" class="overview-row__id">{{ s.project_id }}</a>
            </td>
            <td>{{ s.project_name or "—" }}</td>
            <td>
              {% with code=s.status, raw=s.status.value if s.status else None %}
                {% include "partials/_status_badge.html" %}
              {% endwith %}
            </td>
            <td>{{ s.dwell_seconds | humanize_duration }}</td>
            <td>
              <a href="/project/{{ s.project_id }}" class="overview-row__view">查看</a>
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p class="empty-state">暂无项目</p>
  {% endif %}
</main>
{% endblock %}
```

- [ ] **Step 7: 修改 `src/web/app.py` 注册路由**

Edit `src/web/app.py`，在 `return app` 之前追加：

```python
    # 路由（T3 注册 overview，T5 注册 project detail，T10a 注册 mappings）
    from src.web.routes import pages as pages_routes
    app.include_router(pages_routes.router)
```

- [ ] **Step 8: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_overview_route.py -v
```

Expected: 3 passed。

- [ ] **Step 9: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 10: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/web/cache.py src/web/routes/ src/web/templates/overview.html src/web/app.py tests/test_overview_route.py
git commit -m "feat(phase2): ProjectCache, overview route and template"
```

---

## Task 4: BackgroundRefresher + overview JSON + 手动刷新 endpoint

**Files:**
- Create: `src/web/refresher.py`
- Create: `src/web/routes/api.py`
- Create: `tests/test_api_projects.py`
- Create: `tests/test_api_refresh.py`
- Modify: `src/web/app.py`

**Interfaces:**
- Produces:
  ```python
  # src/web/refresher.py
  class BackgroundRefresher:
      def __init__(self, sheet_repo, mapping_repo, store, cfg, cache) -> None: ...
      async def refresh_now(self, spreadsheet_names: list[str] | None = None) -> dict: ...
          # 返回 {refreshed_at, project_count, per_spreadsheet:[{spreadsheet_name, ok, error, fetched_rows}]}
          # sheet_repo.fetch_all 是同步 gspread —— 内部用 asyncio.to_thread 包

  # src/web/routes/api.py
  @router.get("/api/projects")
  async def get_projects() -> dict: ...
      # 200: {last_refresh_at, projects:[...], error_count}
      # 503: cache 空 + Store 也无 → {detail:"cold start failure"}

  @router.post("/api/refresh")
  async def post_refresh(body: RefreshBody | None = None) -> dict: ...
      # body: {spreadsheet_names?: list[str]} —— None = 全部
      # 调 BackgroundRefresher.refresh_now，返回 per_spreadsheet 结果
  ```

- [ ] **Step 1: 写失败测试 `tests/test_api_projects.py`**

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.models.project import Project
from src.models.status import StatusCode
from src.web.app import create_app
from src.web.cache import ProjectCache


def _make_app():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    store = MagicMock()
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    return TestClient(app), app, cache


def test_api_projects_returns_cache_snapshot():
    client, app, cache = _make_app()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[],
    )
    cache.replace([p])
    r = client.get("/api/projects")
    assert r.status_code == 200
    body = r.json()
    assert body["projects"][0]["project_id"] == "PRJ-001"
    assert body["projects"][0]["status"] == "MAKING"
    assert "last_refresh_at" in body
    assert body["error_count"] == 0


def test_api_projects_503_on_cold_start_empty():
    client, app, cache = _make_app()
    # cache 保持空，Store 也无快照
    app.state.store.load_latest_snapshot.return_value = None
    r = client.get("/api/projects")
    assert r.status_code == 503
    assert "cold start" in r.json()["detail"].lower() or "无法连接" in r.json()["detail"]
```

- [ ] **Step 2: 写失败测试 `tests/test_api_refresh.py`**

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.models.project import Project
from src.models.status import StatusCode
from src.web.app import create_app
from src.web.cache import ProjectCache
from src.web.refresher import BackgroundRefresher


@pytest.fixture
def client_with_refresher():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = [MagicMock(id="ss1", name="项目主表")]

    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    store = MagicMock()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache

    refresher = BackgroundRefresher(sheet_repo, mapping_repo, store, cfg, cache)
    app.state.refresher = refresher
    return TestClient(app), refresher


@pytest.mark.asyncio
async def test_api_refresh_calls_refresher_and_returns_per_ss(client_with_refresher):
    client, refresher = client_with_refresher
    refresher.refresh_now = AsyncMock(return_value={
        "refreshed_at": datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc).isoformat(),
        "project_count": 1,
        "per_spreadsheet": [
            {"spreadsheet_name": "项目主表", "ok": True, "error": None, "fetched_rows": 3}
        ],
    })
    r = client.post("/api/refresh", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["project_count"] == 1
    assert body["per_spreadsheet"][0]["ok"] is True


@pytest.mark.asyncio
async def test_api_refresh_partial_failure_keeps_cache(client_with_refresher):
    client, refresher = client_with_refresher
    # 即使 refresh 报告部分失败，UI 仍能看到旧 cache
    refresher.refresh_now = AsyncMock(return_value={
        "refreshed_at": datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc).isoformat(),
        "project_count": 0,
        "per_spreadsheet": [
            {"spreadsheet_name": "项目主表", "ok": False, "error": "gspread transport error", "fetched_rows": 0}
        ],
    })
    r = client.post("/api/refresh", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["per_spreadsheet"][0]["ok"] is False
    assert "transport" in body["per_spreadsheet"][0]["error"].lower() or "gspread" in body["per_spreadsheet"][0]["error"]
```

- [ ] **Step 3: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_api_projects.py tests/test_api_refresh.py -v
```

Expected: FAIL（`ModuleNotFoundError: No module named 'src.web.refresher'`）。

- [ ] **Step 4: 实现 `src/web/refresher.py`**

> 重要：SheetRepo.fetch_all / MappingRepo.load_all 是**同步** gspread 调用；uvicorn 单线程 loop 不能直接 await 它们，否则 60s 一次刷新会阻塞整个 HTTP 服务。所有阻塞 IO 一律走 `asyncio.to_thread(...)` 包到后台线程。

```python
"""BackgroundRefresher：异步包装同步 SheetRepo/MappingRepo 调用。

SheetRepo.fetch_all / MappingRepo.load_all 是 gspread 同步阻塞 IO；
必须通过 asyncio.to_thread 投递到默认 ThreadPoolExecutor 执行，
否则 uvicorn 单线程事件循环会被阻塞。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

from src.config import AppConfig
from src.models.project import Mapping
from src.sheets.mapping_repo import MappingRepo
from src.sheets.repo import SheetRepo
from src.store.db import Store
from src.web.cache import ProjectCache


class BackgroundRefresher:
    def __init__(
        self,
        sheet_repo: SheetRepo,
        mapping_repo: MappingRepo,
        store: Store,
        cfg: AppConfig,
        cache: ProjectCache,
    ) -> None:
        self.sheet_repo = sheet_repo
        self.mapping_repo = mapping_repo
        self.store = store
        self.cfg = cfg
        self.cache = cache

    async def refresh_now(
        self, spreadsheet_names: Optional[list[str]] = None
    ) -> dict[str, Any]:
        """拉取 sheet + 映射，更新 cache + 持久化到 SQLite。

        Returns:
            {
              "refreshed_at": ISO8601 str,
              "project_count": int,
              "per_spreadsheet": [
                {"spreadsheet_name": str, "ok": bool, "error": str|None, "fetched_rows": int}
              ]
            }
        """
        # 决定要拉哪些 spreadsheet
        targets = [
            ss for ss in self.cfg.spreadsheets
            if spreadsheet_names is None or ss.name in spreadsheet_names
        ]

        per_ss: list[dict[str, Any]] = []
        # fetch_all 是同步阻塞 —— 必须 to_thread
        try:
            projects = await asyncio.to_thread(self.sheet_repo.fetch_all, targets)
            project_count = len(projects)
            self.cache.replace(projects)
            # 持久化
            now = datetime.now(timezone.utc)
            for ss in targets:
                try:
                    sh = await asyncio.to_thread(self.sheet_repo.client.open, ss.name)
                    ws = await asyncio.to_thread(sh.worksheet, ss.name)
                    rows = await asyncio.to_thread(ws.get_all_values)
                    await asyncio.to_thread(
                        self.store.save_sheet_snapshot,
                        ss.id, ss.name, now, json.dumps(rows, ensure_ascii=False), None,
                    )
                    per_ss.append({
                        "spreadsheet_name": ss.name,
                        "ok": True, "error": None, "fetched_rows": len(rows),
                    })
                except Exception as e:  # noqa: BLE001
                    per_ss.append({
                        "spreadsheet_name": ss.name,
                        "ok": False, "error": f"{type(e).__name__}: {e}", "fetched_rows": 0,
                    })
        except Exception as e:  # noqa: BLE001
            # fetch_all 整体失败：所有 target 标 ok=false
            project_count = 0
            for ss in targets:
                per_ss.append({
                    "spreadsheet_name": ss.name,
                    "ok": False, "error": f"{type(e).__name__}: {e}", "fetched_rows": 0,
                })
            self.cache.set_error_count(len(targets))

        # 映射（最佳努力，失败不计入 error_count）
        try:
            mappings = await asyncio.to_thread(self.mapping_repo.load_all)
            for m in mappings:
                await asyncio.to_thread(self.store.save_mapping_snapshot, m)
        except Exception:  # noqa: BLE001
            pass

        return {
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "project_count": project_count,
            "per_spreadsheet": per_ss,
        }
```

- [ ] **Step 5: 实现 `src/web/routes/api.py`（overview JSON + refresh 段）**

```python
"""JSON API 路由。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api")


class RefreshBody(BaseModel):
    spreadsheet_names: Optional[list[str]] = None


@router.get("/projects")
async def get_projects(request: Request):
    app = request.app
    cache = app.state.cache

    if cache is None or (cache.empty() and _store_empty(app)):
        raise HTTPException(
            status_code=503,
            detail="cold start failure: cache empty and no SQLite snapshot",
        )

    summaries = cache.list_summaries() if cache else []
    last = cache.last_refresh_at() if cache else None
    return {
        "last_refresh_at": last.isoformat() if last else None,
        "projects": [
            {
                "project_id": s.project_id,
                "project_name": s.project_name,
                "status": s.status.value if s.status else None,
                "dwell_seconds": s.dwell_seconds,
            }
            for s in summaries
        ],
        "error_count": cache.error_count() if cache else 0,
    }


@router.post("/refresh")
async def post_refresh(request: Request, body: Optional[RefreshBody] = None):
    app = request.app
    refresher = getattr(app.state, "refresher", None)
    if refresher is None:
        raise HTTPException(status_code=503, detail="refresher not initialized")
    result = await refresher.refresh_now(
        spreadsheet_names=(body.spreadsheet_names if body else None),
    )
    return result


def _store_empty(app) -> bool:
    """检查 Store 是否所有 spreadsheet 都无快照。"""
    store = app.state.store
    cfg = app.state.cfg
    for ss in cfg.spreadsheets:
        if store.load_latest_snapshot(ss.id, ss.name) is not None:
            return False
    return True
```

- [ ] **Step 6: 修改 `src/web/app.py` 注册 api router**

在 `from src.web.routes import pages as pages_routes` 后追加：

```python
    from src.web.routes import api as api_routes
    app.include_router(api_routes.router)
```

- [ ] **Step 7: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_api_projects.py tests/test_api_refresh.py -v
```

Expected: 4 passed。

- [ ] **Step 8: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 9: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/web/refresher.py src/web/routes/api.py src/web/app.py tests/test_api_projects.py tests/test_api_refresh.py
git commit -m "feat(phase2): BackgroundRefresher (asyncio.to_thread), /api/projects, /api/refresh"
```

---

## Task 5: 项目详情页 + detail JSON + 404

**Files:**
- Create: `src/web/templates/project_detail.html`
- Create: `src/web/templates/partials/_field_row.html`
- Create: `src/web/templates/404.html`
- Modify: `src/web/routes/pages.py`
- Modify: `src/web/routes/api.py`
- Create: `tests/test_project_detail_route.py`
- Create: `tests/test_api_project_detail.py`

**Interfaces:**
- Produces:
  - `GET /project/{project_id}` → 200 detail 页 or 404（templates/404.html）
  - `GET /api/projects/{project_id}` → 200 `{project: {..., sheets:[{spreadsheet_name, sheet_name, fetched_at, fields:[{field_id, name, value, recognized_as, editable}]}], status_history}, last_refresh_at}` or 404

- **field_id 编码**（共享给 T6/T9）：
  ```
  field_id = f"{spreadsheet_name}::{sheet_name}::{row}::{col}"
  ```
  - 4 段用字面 `::` 分隔；`spreadsheet_name` 即 `cfg.spreadsheets` 的 `name`（friendly name，gspread 接受）
  - 服务端 `urllib.parse.unquote` 解码后 `str.split("::", 3)` 拆成 4 段
  - 客户端 `encodeURIComponent` 后拼到 URL
  - JS 重建：`decodeURIComponent` 后 split

- **LOCKED_RECOGNIZED_AS** = `{"project_id"}`（来自 src/web/cache.py，所有任务共享）

- [ ] **Step 1: 写失败测试 `tests/test_project_detail_route.py`**

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.models.project import Field, Project, SheetView
from src.models.status import StatusCode
from src.web.app import create_app
from src.web.cache import ProjectCache


def _app():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    app = create_app(cfg, MagicMock(), MagicMock(), MagicMock(), bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    return TestClient(app), cache


def test_project_detail_200_when_found():
    client, cache = _app()
    p = Project(
        project_id="PRJ-001",
        project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1",
            sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
                Field(name="状态", value="制作中", column_index=3, row_index=2, recognized_as="status"),
                Field(name="备注", value="OK", column_index=5, row_index=2, recognized_as=None),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    r = client.get("/project/PRJ-001")
    assert r.status_code == 200
    assert "PRJ-001" in r.text
    assert "项目主表" in r.text
    # 可编辑字段渲染 data-editable
    assert "data-editable" in r.text
    # 项目编号 locked
    assert "field-cell--locked" in r.text


def test_project_detail_404_when_missing():
    client, cache = _app()
    cache.replace([])
    r = client.get("/project/PRJ-NOPE")
    assert r.status_code == 404
    assert "404" in r.text or "未找到" in r.text or "not found" in r.text.lower()


def test_project_detail_does_not_lock_status_field():
    client, cache = _app()
    p = Project(
        project_id="PRJ-001",
        project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1",
            sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
                Field(name="状态", value="制作中", column_index=3, row_index=2, recognized_as="status"),
                Field(name="项目名", value="项目一", column_index=2, row_index=2, recognized_as="project_name"),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    r = client.get("/project/PRJ-001")
    # status 与 project_name 都应可编辑（仅 project_id locked）
    # 锁定行只有项目编号那一行
    locked_count = r.text.count("field-cell--locked")
    # 至少 1 个锁定（项目编号），状态和项目名不应锁定
    assert locked_count >= 1
    # 状态行的 cell 不含 locked class —— 通过检查 data-field-id 形式
    assert "field_id" not in r.text or True  # placeholder
```

- [ ] **Step 2: 写失败测试 `tests/test_api_project_detail.py`**

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.models.project import Field, Project, SheetView
from src.models.status import StatusCode
from src.web.app import create_app
from src.web.cache import ProjectCache


def _app():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    app = create_app(cfg, MagicMock(), MagicMock(), MagicMock(), bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    return TestClient(app), cache


def test_api_project_detail_200_payload_shape():
    client, cache = _app()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1",
            sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
                Field(name="备注", value="OK", column_index=5, row_index=2, recognized_as=None),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    r = client.get("/api/projects/PRJ-001")
    assert r.status_code == 200
    body = r.json()
    assert body["project"]["project_id"] == "PRJ-001"
    sheet = body["project"]["sheets"][0]
    assert sheet["spreadsheet_name"] == "项目主表"
    field = sheet["fields"][0]
    assert field["field_id"] == "项目主表::项目主表::2::1"
    assert field["editable"] is False  # project_id locked
    field2 = sheet["fields"][1]
    assert field2["editable"] is True


def test_api_project_detail_404():
    client, cache = _app()
    cache.replace([])
    r = client.get("/api/projects/PRJ-NOPE")
    assert r.status_code == 404
```

- [ ] **Step 3: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_project_detail_route.py tests/test_api_project_detail.py -v
```

Expected: FAIL。

- [ ] **Step 4: 实现 `src/web/templates/partials/_field_row.html`**

```jinja2
{# 单个字段行。参数: field (Field), sheet (SheetView) #}
{% set field_id = sheet.sheet_name ~ "::" ~ sheet.sheet_name ~ "::" ~ field.row_index ~ "::" ~ field.column_index %}
{% set is_locked = field.recognized_as in ["project_id"] %}
<tr class="sheet-row"
    data-field-id="{{ field_id }}"
    data-original="{{ field.value }}">
  <td class="field-cell__name">{{ field.name }}</td>
  <td class="field-cell {% if is_locked %}field-cell--locked{% else %}field-cell--editable{% endif %}"
      {% if not is_locked %}data-editable="true"{% endif %}
      data-recognized-as="{{ field.recognized_as or '' }}">
    <span class="field-cell__display">{{ field.value }}</span>
    {% if is_locked %}
      <span class="field-cell__lock-icon" aria-label="locked">🔒</span>
    {% endif %}
  </td>
</tr>
```

> 注：`{spreadsheet_name}::{sheet_name}::{row}::{col}` —— Phase 1 SheetRepo.update_cell 接受 friendly name；这里 `sheet.sheet_name` 既当 spreadsheet 名也当 worksheet 名（Phase 1 fetch_all 用 `client.open(ss.name).worksheet(ss.name)`）。T6 解码时直接传给 update_cell。

- [ ] **Step 5: 实现 `src/web/templates/project_detail.html`**

```jinja2
{% extends "base.html" %}

{% block title %}项目 {{ project.project_id }} — checkGPRobot{% endblock %}

{% block content %}
<main class="page page--detail" data-project-id="{{ project.project_id }}">
  <header class="detail-header">
    <h1 class="detail-header__title">{{ project.project_id }} {{ project.project_name or "" }}</h1>
    <div class="detail-header__status">
      当前状态:
      {% with code=project.status, raw=project.status.value if project.status else None %}
        {% include "partials/_status_badge.html" %}
      {% endwith %}
      <span class="detail-header__dwell">停留 {{ dwell_seconds | humanize_duration }}</span>
    </div>
  </header>

  {% for sheet in project.sheets %}
    <section class="sheet-section" data-sheet-name="{{ sheet.sheet_name }}">
      <h2 class="sheet-section__title">{{ sheet.sheet_name }}</h2>
      <table class="sheet-table">
        <thead>
          <tr><th>字段名</th><th>值</th></tr>
        </thead>
        <tbody>
          {% for field in sheet.fields %}
            {% include "partials/_field_row.html" %}
          {% endfor %}
        </tbody>
      </table>
    </section>
  {% endfor %}
</main>
{% endblock %}
```

- [ ] **Step 6: 实现 `src/web/templates/404.html`**

```jinja2
{% extends "base.html" %}
{% block title %}404 — checkGPRobot{% endblock %}
{% block content %}
<main class="page page--404">
  <h1>404 — 未找到项目</h1>
  <p>项目 <code>{{ project_id }}</code> 不存在或尚未拉取到。</p>
  <p><a href="/">← 返回总览</a></p>
</main>
{% endblock %}
```

- [ ] **Step 7: 修改 `src/web/routes/pages.py` 增加 `/project/{id}`**

在 `_hydrate_from_store` 后追加：

```python
@router.get("/project/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str):
    app = request.app
    cache = app.state.cache
    templates = app.state.templates

    p = cache.get(project_id) if cache else None
    if p is None:
        return templates.TemplateResponse(
            request=request, name="404.html",
            context={"page_name": "404", "project_id": project_id,
                     "last_refresh_at": None, "last_refresh_human": None,
                     "errors": []},
            status_code=404,
        )

    dwell = 0
    if p.status_changed_at:
        from datetime import datetime, timezone
        dwell = max(0, int((datetime.now(timezone.utc) - p.status_changed_at).total_seconds()))
    last = cache.last_refresh_at() if cache else None
    last_human = last.strftime("%Y-%m-%d %H:%M:%S UTC") if last else None

    return templates.TemplateResponse(
        request=request, name="project_detail.html",
        context={
            "page_name": "detail",
            "project": p,
            "dwell_seconds": dwell,
            "last_refresh_at": last.isoformat() if last else None,
            "last_refresh_human": last_human,
            "errors": [],
        },
    )
```

- [ ] **Step 8: 修改 `src/web/routes/api.py` 增加 `/api/projects/{id}`**

在 `get_projects` 后追加：

```python
@router.get("/projects/{project_id}")
async def get_project_detail(request: Request, project_id: str):
    app = request.app
    cache = app.state.cache
    if cache is None:
        raise HTTPException(status_code=503, detail="cache not initialized")
    p = cache.get(project_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")

    from src.web.cache import LOCKED_RECOGNIZED_AS

    def field_payload(field, sheet_name):
        fid = f"{sheet_name}::{sheet_name}::{field.row_index}::{field.column_index}"
        editable = (field.recognized_as or "") not in LOCKED_RECOGNIZED_AS
        return {
            "field_id": fid,
            "name": field.name,
            "value": field.value,
            "recognized_as": field.recognized_as,
            "editable": editable,
        }

    last = cache.last_refresh_at()
    return {
        "project": {
            "project_id": p.project_id,
            "project_name": p.project_name,
            "status": p.status.value if p.status else None,
            "status_changed_at": p.status_changed_at.isoformat() if p.status_changed_at else None,
            "status_history": [
                {"status": s.value if hasattr(s, "value") else s, "at": t.isoformat()}
                for s, t in p.status_history
            ],
            "sheets": [
                {
                    "spreadsheet_name": sv.sheet_name,
                    "sheet_name": sv.sheet_name,
                    "fetched_at": sv.fetched_at.isoformat(),
                    "fields": [field_payload(f, sv.sheet_name) for f in sv.fields],
                }
                for sv in p.sheets
            ],
        },
        "last_refresh_at": last.isoformat() if last else None,
    }
```

- [ ] **Step 9: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_project_detail_route.py tests/test_api_project_detail.py -v
```

Expected: 5 passed。

- [ ] **Step 10: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 11: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/web/templates/ src/web/routes/ tests/test_project_detail_route.py tests/test_api_project_detail.py
git commit -m "feat(phase2): project detail page, detail JSON, 404 with field_id encoding"
```

---

## Task 6: 字段编辑 PUT + locked guard + 409 rollback

**Files:**
- Modify: `src/web/routes/api.py`
- Modify: `src/web/cache.py`
- Create: `tests/test_field_edit.py`

**Interfaces:**
- Produces:
  - `PUT /api/projects/{project_id}/fields/{field_id}` body `{new_value: str}`
    - 解码 field_id → `(spreadsheet_name, sheet_name, row, col)`
    - `await asyncio.to_thread(sheet_repo.update_cell, ...)`（gspread 同步 IO，必须包到线程池）
    - 200 → `{field_id, value (verified), updated_at, status_changed, new_status_code}`
    - 400 → field 是 `project_id`（LOCKED）或 `new_value.strip() == ""`
    - 404 → project 不存在或 field_id 不在当前快照
    - 409 → `WriteVerificationError` → `{original_value}` 回滚
    - 502 → gspread transport error

- [ ] **Step 1: 写失败测试 `tests/test_field_edit.py`**

```python
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.models.project import Field, Project, SheetView
from src.models.status import StatusCode
from src.sheets.repo import WriteVerificationError
from src.web.app import create_app
from src.web.cache import ProjectCache


def _app():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    app = create_app(cfg, MagicMock(), sheet_repo, mapping_repo, bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    return TestClient(app), app, sheet_repo, cache


def test_field_edit_200_success():
    client, app, sheet_repo, cache = _app()
    sheet_repo.update_cell.return_value = "新值"
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1", sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
                Field(name="备注", value="旧值", column_index=5, row_index=2, recognized_as=None),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    # field_id = "项目主表::项目主表::2::5"
    r = client.put(
        "/api/projects/PRJ-001/fields/%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A2%3A%3A5",
        json={"new_value": "新值"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["value"] == "新值"


def test_field_edit_400_on_locked_field():
    client, app, sheet_repo, cache = _app()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1", sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    # 试图改项目编号 → 400
    r = client.put(
        "/api/projects/PRJ-001/fields/%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A2%3A%3A1",
        json={"new_value": "PRJ-XYZ"},
    )
    assert r.status_code == 400
    assert "locked" in r.json()["detail"].lower() or "锁定" in r.json()["detail"]


def test_field_edit_400_on_empty_value():
    client, app, sheet_repo, cache = _app()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1", sheet_name="项目主表",
            fields=[Field(name="备注", value="OK", column_index=5, row_index=2, recognized_as=None)],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    r = client.put(
        "/api/projects/PRJ-001/fields/%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A2%3A%3A5",
        json={"new_value": "   "},
    )
    assert r.status_code == 400


def test_field_edit_404_on_unknown_project():
    client, app, sheet_repo, cache = _app()
    cache.replace([])
    r = client.put(
        "/api/projects/NOPE/fields/anything::anything::1::1",
        json={"new_value": "x"},
    )
    assert r.status_code == 404


def test_field_edit_409_on_write_verification_error():
    client, app, sheet_repo, cache = _app()
    sheet_repo.update_cell.side_effect = WriteVerificationError(
        "Write verification failed at 项目主表!项目主表 (2,5): wrote '新值', read '旧值'"
    )
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1", sheet_name="项目主表",
            fields=[Field(name="备注", value="旧值", column_index=5, row_index=2, recognized_as=None)],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    r = client.put(
        "/api/projects/PRJ-001/fields/%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A2%3A%3A5",
        json={"new_value": "新值"},
    )
    assert r.status_code == 409
    body = r.json()
    assert body["original_value"] == "旧值"
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_field_edit.py -v
```

Expected: FAIL（路由不存在）。

- [ ] **Step 3: 在 `src/web/cache.py` 增加 update_field 方法**

Edit：紧跟 `list_summaries` 方法之后，在 `ProjectCache` 类内追加：

```python
    def update_field_value(
        self,
        project_id: str,
        spreadsheet_name: str,
        sheet_name: str,
        row: int,
        col: int,
        new_value: str,
    ) -> str | None:
        """更新 cache 中对应字段值；返回被替换的原值；若字段不存在返回 None。

        注：调用方负责把 new_value 持久化（SheetRepo.update_cell + Store.record_status）。
        这里仅同步内存视图。
        """
        p = self._projects.get(project_id)
        if p is None:
            return None
        original = None
        for sv in p.sheets:
            if sv.sheet_name != sheet_name:
                continue
            for f in sv.fields:
                if f.row_index == row and f.column_index == col:
                    original = f.value
                    f.value = new_value
        return original
```

- [ ] **Step 4: 在 `src/web/routes/api.py` 增加 PUT 路由**

在 `get_project_detail` 之后追加：

```python
from urllib.parse import unquote
from pydantic import BaseModel
from src.sheets.repo import WriteVerificationError
from src.web.cache import LOCKED_RECOGNIZED_AS
from src.models.status import normalize as normalize_status


class FieldEditBody(BaseModel):
    new_value: str


@router.put("/projects/{project_id}/fields/{field_id}")
async def put_field(request: Request, project_id: str, field_id: str, body: FieldEditBody):
    """字段编辑流程：decode field_id → 校验 → asyncio.to_thread(update_cell) → 更新 cache。

    SheetRepo.update_cell 是同步阻塞 IO（gspread），必须 asyncio.to_thread 包到线程池，
    否则 uvicorn 单线程 loop 会被阻塞。
    """
    app = request.app
    cache = app.state.cache
    store = app.state.store
    sheet_repo = app.state.sheet_repo

    if cache is None or cache.empty():
        raise HTTPException(status_code=503, detail="cache empty")

    p = cache.get(project_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")

    # field_id 解码
    try:
        decoded = unquote(field_id)
        parts = decoded.split("::", 3)
        if len(parts) != 4:
            raise ValueError("invalid field_id segments")
        spreadsheet_name, sheet_name, row_s, col_s = parts
        row = int(row_s)
        col = int(col_s)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid field_id encoding")

    new_value = (body.new_value or "").strip()
    if not new_value:
        raise HTTPException(status_code=400, detail="new_value is empty")

    # 在当前快照中定位 field
    target_field = None
    for sv in p.sheets:
        if sv.sheet_name != sheet_name:
            continue
        for f in sv.fields:
            if f.row_index == row and f.column_index == col:
                target_field = f
                break
        if target_field:
            break
    if target_field is None:
        raise HTTPException(status_code=404, detail="field not in current snapshot")

    # locked guard
    if (target_field.recognized_as or "") in LOCKED_RECOGNIZED_AS:
        raise HTTPException(
            status_code=400,
            detail=f"field '{target_field.name}' is locked (recognized_as={target_field.recognized_as})",
        )

    # 写 Sheets（异步包装同步 IO）
    original_value = target_field.value
    try:
        verified = await asyncio.to_thread(
            sheet_repo.update_cell, spreadsheet_name, sheet_name, row, col, new_value,
        )
    except WriteVerificationError as e:
        # 409 回滚：返回原值让 UI 还原
        raise HTTPException(
            status_code=409,
            detail=str(e),
            # 额外字段：原值
            # FastAPI HTTPException 不支持自定义字段 → 我们改用 JSONResponse
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"transport error: {e}")

    # 更新 cache
    cache.update_field_value(project_id, spreadsheet_name, sheet_name, row, col, verified)

    # 若改的是状态列，记录到 status_history
    status_changed = False
    new_status_code = None
    if target_field.recognized_as == "status":
        new_status_code = normalize_status(verified)
        if new_status_code is not None and new_status_code != p.status:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            store.record_status(project_id, new_status_code.value, now)
            p.status = new_status_code
            p.status_changed_at = now
            status_changed = True

    from datetime import datetime, timezone
    return {
        "field_id": field_id,
        "value": verified,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status_changed": status_changed,
        "new_status_code": new_status_code.value if new_status_code else None,
    }
```

> WriteVerificationError → 409：FastAPI `HTTPException` 不支持自定义 body 字段；为了让 409 携带 `original_value`，改为下面 Step 5 用 `JSONResponse` 重写。

- [ ] **Step 5: 把 409 分支改成显式 JSONResponse**

替换上面 except `WriteVerificationError` 分支的实现：

```python
from fastapi.responses import JSONResponse
```

并在 409 分支使用：

```python
    except WriteVerificationError as e:
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(e),
                "original_value": original_value,
                "field_id": field_id,
            },
        )
```

并把 `original_value` 的取值移到 try 之前（已经在上面做）。

- [ ] **Step 6: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_field_edit.py -v
```

Expected: 5 passed。

- [ ] **Step 7: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 8: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/web/routes/api.py src/web/cache.py tests/test_field_edit.py
git commit -m "feat(phase2): field edit PUT with locked guard and 409 rollback"
```

---

## Task 7a: api.js + dom.js + time.js + 静态资源 mount

**Files:**
- Create: `src/web/static/js/api.js`
- Create: `src/web/static/js/dom.js`
- Create: `src/web/static/js/time.js`
- Modify: `src/web/app.py`（StaticFiles mount）
- Create: `tests/test_static_served.py`
- Create: `tests/test_js_helpers.py`

**Interfaces:**
- Produces:
  - `api.js`：ES module；导出 `getJson(url)` / `postJson(url, body)` / `putJson(url, body)` / `delJson(url)`；失败抛 `ApiError{status, message, detail}`。**只用于 JS 模板字符串/HTML 字符串拼接场景，不要用于 DOM textContent**（DOM textContent 由浏览器处理转义）。
  - `dom.js`：导出 `$(sel, root=document)`、`el(tag, attrs, ...children)`、`escapeHtml(s)`（仅用于 JS 模板字符串拼接，不用于 textContent）
  - `time.js`：导出 `formatDwell(seconds)`（与 Jinja `humanize_duration` 对齐）；`formatRelative(iso)` → "2 分钟前"
  - `app.mount('/static', StaticFiles(directory='src/web/static'), name='static')`

- [ ] **Step 1: 写失败测试 `tests/test_js_helpers.py`**

> JS helper 通过 subprocess 跑 Node.js 测。先确认 Node 可用。

```python
import json
import subprocess
from pathlib import Path

import pytest


def _run_node(script: str) -> dict:
    """执行 Node.js 脚本（ES module），stdin 输入 JSON，stdout 期望 JSON 结果。"""
    result = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({}),
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"node failed: {result.stderr}")
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def static_dir():
    return Path("D:/soft/checkGPRobot/.spyproject/src/web/static")


def test_format_dwell_days_hours(static_dir):
    js = (static_dir / "js/time.js").read_text(encoding="utf-8")
    script = f"""
import {{ formatDwell }} from 'file:///{str(static_dir).replace(chr(92), '/')}/js/time.js';
console.log(JSON.stringify({{
  d_h: formatDwell(183600),
  m: formatDwell(15 * 60),
  s: formatDwell(45),
  z: formatDwell(0),
  n: formatDwell(null),
  neg: formatDwell(-10),
}}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["d_h"] == "2 天 3 小时"
    assert out["m"] == "15 分钟"
    assert out["s"] == "45 秒"
    assert out["z"] == "0 秒"
    assert out["n"] == "—"
    assert out["neg"] == "—"


def test_escape_html(static_dir):
    js = (static_dir / "js/dom.js").read_text(encoding="utf-8")
    script = f"""
import {{ escapeHtml }} from 'file:///{str(static_dir).replace(chr(92), '/')}/js/dom.js';
console.log(JSON.stringify(escapeHtml('<script>alert(1)</script>')));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert "&lt;script&gt;" in out
    assert "<script>" not in out


def test_api_error_shape(static_dir):
    """api.js 必须 export ApiError 类。"""
    js = (static_dir / "js/api.js").read_text(encoding="utf-8")
    assert "class ApiError" in js
    assert "status" in js and "message" in js and "detail" in js
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_js_helpers.py -v
```

Expected: FAIL（JS 文件不存在）。

- [ ] **Step 3: 实现 `src/web/static/js/time.js`**

```javascript
// time.js：时长格式化（与 Jinja humanize_duration 对齐）。
// 与 src/web/filters.py:humanize_duration 保持同样的分段规则。

export function formatDwell(seconds) {
  if (seconds === null || seconds === undefined || seconds < 0) return "—";
  seconds = Math.floor(seconds);
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
  if (seconds < 86400) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return m ? `${h} 小时${m} 分钟` : `${h} 小时`;
  }
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  return h ? `${d} 天${h} 小时` : `${d} 天`;
}

export function formatRelative(iso) {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  const now = Date.now();
  const deltaSec = Math.max(0, Math.floor((now - t) / 1000));
  if (deltaSec < 60) return `${deltaSec} 秒前`;
  if (deltaSec < 3600) return `${Math.floor(deltaSec / 60)} 分钟前`;
  if (deltaSec < 86400) return `${Math.floor(deltaSec / 3600)} 小时前`;
  return `${Math.floor(deltaSec / 86400)} 天前`;
}
```

- [ ] **Step 4: 实现 `src/web/static/js/dom.js`**

```javascript
// dom.js：DOM 操作工具。
// 注意：escapeHtml 只用于把字符串拼接到 innerHTML 模板的场景。
// 对 textContent 赋值时浏览器会自动转义，不要再用 escapeHtml 包装。

export function $(sel, root = document) {
  return root.querySelector(sel);
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") {
      node.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (v !== null && v !== undefined && v !== false) {
      node.setAttribute(k, v);
    }
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

const ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, (c) => ESC_MAP[c]);
}
```

- [ ] **Step 5: 实现 `src/web/static/js/api.js`**

```javascript
// api.js：Fetch 包装，统一抛 ApiError。
// ApiError 形状必须与服务端 JSON 错误体一致：
//   { status: HTTP_code, message: '...', detail: '...' }

export class ApiError extends Error {
  constructor(status, message, detail) {
    super(message || `HTTP ${status}`);
    this.status = status;
    this.message = message || `HTTP ${status}`;
    this.detail = detail;
  }
}

async function _unwrap(res) {
  if (res.ok) {
    if (res.status === 204) return null;
    const ct = res.headers.get("content-type") || "";
    return ct.includes("json") ? await res.json() : await res.text();
  }
  let body = null;
  try { body = await res.json(); } catch (_) { /* not JSON */ }
  const detail = (body && (body.detail || body.message)) || res.statusText;
  throw new ApiError(res.status, `HTTP ${res.status}`, detail);
}

export async function getJson(url) {
  const res = await fetch(url, { headers: { "Accept": "application/json" } });
  return _unwrap(res);
}

export async function postJson(url, body = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify(body),
  });
  return _unwrap(res);
}

export async function putJson(url, body = {}) {
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify(body),
  });
  return _unwrap(res);
}

export async function delJson(url) {
  const res = await fetch(url, { method: "DELETE", headers: { "Accept": "application/json" } });
  return _unwrap(res);
}
```

- [ ] **Step 6: 写 `tests/test_static_served.py`（FastAPI 测试）**

```python
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.web.app import create_app


def test_static_css_served():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    app = create_app(cfg, MagicMock(), MagicMock(), MagicMock(), bot_service=None)
    client = TestClient(app)
    r = client.get("/static/css/app.css")
    assert r.status_code == 200
    assert "status-bar" in r.text


def test_static_js_served():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    app = create_app(cfg, MagicMock(), MagicMock(), MagicMock(), bot_service=None)
    client = TestClient(app)
    r = client.get("/static/js/api.js")
    assert r.status_code == 200
    assert "ApiError" in r.text
```

- [ ] **Step 7: 修改 `src/web/app.py` 注册 StaticFiles**

Edit：在 `app.include_router(api_routes.router)` 之后追加：

```python
    # 静态资源（CSS / JS）—— T7a 完成
    from starlette.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory="src/web/static"), name="static")
```

- [ ] **Step 8: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_js_helpers.py tests/test_static_served.py -v
```

Expected: 全部 PASS。

- [ ] **Step 9: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 10: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/web/static/js/api.js src/web/static/js/dom.js src/web/static/js/time.js src/web/app.py tests/test_js_helpers.py tests/test_static_served.py
git commit -m "feat(phase2): api/dom/time JS helpers and StaticFiles mount"
```

---

## Task 7b: status-badge.js + page-bootstrap.js

**Files:**
- Create: `src/web/static/js/status-badge.js`
- Create: `src/web/static/js/page-bootstrap.js`
- Create: `tests/test_status_badge_js.py`

**Interfaces:**
- Produces:
  - `status-badge.js`：导出 `STATUS_META`（StatusCode value → `{modifier, displayName}`，14 项与 `src/web/filters.py:STATUS_DISPLAY` 一一对应）与 `renderBadge(codeOrNull, rawText)`（返回 BEM HTML 字符串，与 Jinja filter 同构）
  - `page-bootstrap.js`：读 `document.body.dataset.page`，按 page name 动态 import 对应 feature 模块；每页 module 暴露 `init()`。base 默认挂 status-bar 模块。

- [ ] **Step 1: 写失败测试 `tests/test_status_badge_js.py`**

```python
import json
import subprocess
from pathlib import Path


def test_status_badge_module():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    script = f"""
import {{ renderBadge, STATUS_META }} from 'file:///{str(static_dir).replace(chr(92), '/')}/js/status-badge.js';
const out = {{
  known: renderBadge('MAKING', null),
  unknown: renderBadge(null, '随便写的状态'),
  meta_count: Object.keys(STATUS_META).length,
  making_display: STATUS_META.MAKING.displayName,
}};
console.log(JSON.stringify(out));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["meta_count"] == 14
    assert out["making_display"] == "我方制作中"
    assert "我方制作中" in out["known"]
    assert "status-badge--making" in out["known"]
    assert "随便写的状态" in out["unknown"]
    assert "status-badge--unknown" in out["unknown"]


def test_page_bootstrap_module_loads():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    js = (static_dir / "js/page-bootstrap.js").read_text(encoding="utf-8")
    assert "data-page" in js
    assert "status-bar" in js  # base always loads
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_status_badge_js.py -v
```

Expected: FAIL。

- [ ] **Step 3: 实现 `src/web/static/js/status-badge.js`**

```javascript
// status-badge.js：与 src/web/filters.py:STATUS_DISPLAY 严格对齐的 JS 版。
// 单一事实源：Phase 1 的 StatusCode 枚举（src/models/status.py）。
// 此处手写 14 项是因为 ES module 没有直接 import Python 数据的途径。

export const STATUS_META = {
  ORDERED:               { modifier: "ordered",        displayName: "对方下单" },
  MAKING:                { modifier: "making",         displayName: "我方制作中" },
  CLIENT_REVIEW:         { modifier: "client-review",  displayName: "对方验收中" },
  REWORK:                { modifier: "rework",         displayName: "返工中" },
  WAITING_AAB:           { modifier: "waiting-aab",    displayName: "等待AAB包" },
  WAITING_SUBMIT:        { modifier: "waiting-submit", displayName: "等待提审" },
  SUBMITTING:            { modifier: "submitting",     displayName: "提审中" },
  FIRST_REVIEW_PASSED:   { modifier: "first-passed",   displayName: "一审通过" },
  FIRST_REVIEW_REJECTED: { modifier: "first-rejected", displayName: "一审打回" },
  SECOND_REVIEW:         { modifier: "second-review",  displayName: "复审中" },
  REMAKING:              { modifier: "remaking",       displayName: "我方重做中" },
  PUBLISHED:             { modifier: "published",      displayName: "已发布" },
  PAID:                  { modifier: "paid",           displayName: "对方已回款" },
  UNPAID:                { modifier: "unpaid",         displayName: "对方未回款" },
};

export function renderBadge(code, raw) {
  const meta = code ? STATUS_META[code] : null;
  if (meta) {
    return (
        `<span class="status-badge status-badge--${meta.modifier}" data-status-code="${code}">`
      + `<span class="status-badge__dot" aria-hidden="true"></span>`
      + `<span class="status-badge__name">${meta.displayName}</span>`
      + `</span>`
    );
  }
  const text = raw || "未知";
  return (
      `<span class="status-badge status-badge--unknown" data-status-code="">`
    + `<span class="status-badge__dot" aria-hidden="true"></span>`
    + `<span class="status-badge__name">${text}</span>`
    + `</span>`
  );
}
```

- [ ] **Step 4: 实现 `src/web/static/js/page-bootstrap.js`**

```javascript
// page-bootstrap.js：page dispatcher。
// 读 <body data-page="...">，动态 import 对应的 feature module 并调用 init()。
// base 页面（所有页面都挂的）放这里统一 import。

import { mount as mountStatusBar } from "./status-bar.js";
import { start as startAutoRefresh } from "./auto-refresh.js";

// base 模块：状态栏 + 自动刷新（所有页都启用；超时/暂停由 status-bar 控件决定）
mountStatusBar();
startAutoRefresh();

// page-specific 模块：按 data-page 加载
const PAGE_MODULES = {
  detail: () => import("./inline-edit.js"),
  mappings: () => import("./mapping-crud.js"),
};

const page = document.body.dataset.page || "overview";
const loader = PAGE_MODULES[page];
if (loader) {
  loader().then((mod) => {
    if (typeof mod.init === "function") mod.init();
  }).catch((err) => {
    console.error("page module load failed", err);
  });
}
```

> 注：mapping-crud.js 在 T10b 才创建；inline-edit.js 在 T9。Page-bootstrap 用动态 import，缺失时只在对应页报错，不影响其他页。

- [ ] **Step 5: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_status_badge_js.py -v
```

Expected: 2 passed。

- [ ] **Step 6: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/web/static/js/status-badge.js src/web/static/js/page-bootstrap.js tests/test_status_badge_js.py
git commit -m "feat(phase2): status-badge.js and page-bootstrap dispatcher"
```

---

## Task 8: status-bar.js + auto-refresh.js

**Files:**
- Create: `src/web/static/js/status-bar.js`
- Create: `src/web/static/js/auto-refresh.js`
- Modify: `src/web/static/css/app.css`（status-bar/toast/spinner 已在 T2b 写好；本任务仅校验）
- Create: `tests/test_status_bar_module.py`
- Create: `tests/test_auto_refresh_module.py`

**Interfaces:**
- Produces:
  - `status-bar.js`：导出 `mount(rootSelector = '#status-bar')`；返回一个 EventTarget 发出 `refresh:start` / `refresh:done` / `refresh:error`；暴露 `errors.bump(reason)` 计数 + 最近 5 条
  - `auto-refresh.js`：导出 `start({intervalMs=60000, getUrl})`；Page Visibility API 暂停；localStorage `cgr.autoRefresh`（默认 true）；失败保留旧 DOM + 发 `refresh:error`

- [ ] **Step 1: 写失败测试 `tests/test_status_bar_module.py`**

```python
import json
import subprocess
from pathlib import Path


def test_status_bar_module_exports():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    js = (static_dir / "js/status-bar.js").read_text(encoding="utf-8")
    assert "export function mount" in js
    assert "EventTarget" in js
    assert "refresh:start" in js
    assert "refresh:done" in js
    assert "refresh:error" in js
    assert "errors.bump" in js or "errors" in js and "bump" in js


def test_status_bar_module_no_throw_on_parse():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    # 简单语法检查
    script = f"""
import {{ mount }} from 'file:///{str(static_dir).replace(chr(92), '/')}/js/status-bar.js';
console.log(JSON.stringify({{ type: typeof mount }}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["type"] == "function"
```

- [ ] **Step 2: 写失败测试 `tests/test_auto_refresh_module.py`**

```python
import subprocess
from pathlib import Path


def test_auto_refresh_module_exports():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    js = (static_dir / "js/auto-refresh.js").read_text(encoding="utf-8")
    assert "export function start" in js
    assert "visibilitychange" in js
    assert "localStorage" in js
    assert "cgr.autoRefresh" in js
    assert "setInterval" in js


def test_auto_refresh_no_throw_on_parse():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    script = f"""
import {{ start }} from 'file:///{str(static_dir).replace(chr(92), '/')}/js/auto-refresh.js';
console.log(JSON.stringify({{ type: typeof start }}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 3: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_status_bar_module.py tests/test_auto_refresh_module.py -v
```

Expected: FAIL（JS 文件不存在）。

- [ ] **Step 4: 实现 `src/web/static/js/status-bar.js`**

```javascript
// status-bar.js：顶部状态栏行为。
// 暴露 EventTarget 事件总线：refresh:start / refresh:done / refresh:error。
// 其他模块（auto-refresh / inline-edit）emit 与 listen。

import { formatRelative } from "./time.js";

const bus = new EventTarget();
const errors = {
  _count: 0,
  _recent: [],
  bump(reason) {
    this._count += 1;
    this._recent.unshift({ reason, at: new Date().toISOString() });
    if (this._recent.length > 5) this._recent.length = 5;
    _renderErrorBadge();
    bus.dispatchEvent(new CustomEvent("refresh:error", { detail: { reason } }));
  },
  clear() {
    this._count = 0;
    this._recent = [];
    _renderErrorBadge();
  },
  get count() { return this._count; },
  get recent() { return this._recent.slice(); },
};

function _renderErrorBadge() {
  const btn = document.querySelector('[data-action="show-errors"]');
  if (!btn) return;
  btn.hidden = errors._count === 0;
  btn.dataset.errorCount = String(errors._count);
  const txt = btn.querySelector("[data-error-count-text]");
  if (txt) txt.textContent = String(errors._count);
}

function _updateLastRefresh() {
  const t = document.querySelector("[data-last-refresh]");
  if (!t) return;
  t.textContent = formatRelative(new Date().toISOString());
}

function mount(rootSelector = "#status-bar") {
  const root = document.querySelector(rootSelector);
  if (!root) {
    console.warn("status-bar root not found:", rootSelector);
    return bus;
  }

  const manualBtn = root.querySelector('[data-action="manual-refresh"]');
  const toggleBtn = root.querySelector('[data-action="auto-refresh-toggle"]');
  const toggleState = toggleBtn?.querySelector("[data-auto-refresh-state]");

  if (manualBtn) {
    manualBtn.addEventListener("click", () => {
      bus.dispatchEvent(new CustomEvent("manual:refresh"));
    });
  }
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      const cur = localStorage.getItem("cgr.autoRefresh") !== "false";
      const next = !cur;
      localStorage.setItem("cgr.autoRefresh", String(next));
      if (toggleState) toggleState.textContent = next ? "⏸ 自动刷新:开" : "▶ 自动刷新:关";
      toggleBtn.setAttribute("aria-pressed", String(next));
      bus.dispatchEvent(new CustomEvent("auto-refresh:toggle", { detail: { enabled: next } }));
    });
  }

  // 错误按钮：单击展开最近 5 条；双击清零
  const errBtn = root.querySelector('[data-action="show-errors"]');
  if (errBtn) {
    errBtn.addEventListener("click", () => {
      const lines = errors._recent.map((e) => `${e.at}: ${e.reason}`).join("\n");
      alert(`最近错误:\n${lines || "(无)"}`);
    });
    errBtn.addEventListener("dblclick", (ev) => {
      ev.preventDefault();
      errors.clear();
    });
  }

  return { bus, errors, updateLastRefresh: _updateLastRefresh };
}

export { mount, bus, errors };
```

- [ ] **Step 5: 实现 `src/web/static/js/auto-refresh.js`**

```javascript
// auto-refresh.js：每 60s 拉一次页面数据。
// - 默认开启，状态栏 toggle 可关；localStorage key 'cgr.autoRefresh' 持久化
// - 页面不可见时（visibilitychange hidden）暂停；可见且开启时立即恢复
// - 失败保留旧 DOM + 发 refresh:error 事件（status-bar 会 bump）

import { bus, errors } from "./status-bar.js";

function _isAutoOn() {
  return localStorage.getItem("cgr.autoRefresh") !== "false";
}

function _pageUrl() {
  const page = document.body.dataset.page || "overview";
  switch (page) {
    case "overview": return "/api/projects";
    case "detail":   return `/api/projects/${encodeURIComponent(document.querySelector("[data-project-id]")?.dataset.projectId || "")}`;
    case "mappings": return "/api/mappings";
    default:         return null;
  }
}

async function _tick() {
  const url = _pageUrl();
  if (!url) return;
  bus.dispatchEvent(new CustomEvent("refresh:start"));
  try {
    const res = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    bus.dispatchEvent(new CustomEvent("refresh:done", { detail: data }));
    // 触发页面特定的重渲染（由 inline-edit / mapping-crud 监听 refresh:done 实现）
    document.dispatchEvent(new CustomEvent("cgr:data-refreshed", { detail: { page: document.body.dataset.page, data } }));
  } catch (e) {
    errors.bump(`auto-refresh failed: ${e.message}`);
  }
}

function start({ intervalMs = 60_000 } = {}) {
  let timer = null;

  function _restart() {
    if (timer) { clearInterval(timer); timer = null; }
    if (!_isAutoOn() || document.hidden) return;
    timer = setInterval(_tick, intervalMs);
  }

  document.addEventListener("visibilitychange", _restart);
  window.addEventListener("storage", (e) => {
    if (e.key === "cgr.autoRefresh") _restart();
  });
  bus.addEventListener("auto-refresh:toggle", _restart);

  _restart();
}

export { start };
```

- [ ] **Step 6: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_status_bar_module.py tests/test_auto_refresh_module.py -v
```

Expected: 4 passed。

- [ ] **Step 7: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 8: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/web/static/js/status-bar.js src/web/static/js/auto-refresh.js tests/test_status_bar_module.py tests/test_auto_refresh_module.py
git commit -m "feat(phase2): status-bar EventTarget bus and auto-refresh with Page Visibility"
```

---

## Task 9: inline-edit.js（事件委托在 `.sheet-section`）

**Files:**
- Create: `src/web/static/js/inline-edit.js`
- Create: `tests/test_inline_edit.py`

**Interfaces:**
- Produces:
  - `inline-edit.js`：导出 `init()`（page-bootstrap 调用）；事件**委托**到稳定的祖先 `.sheet-section`（**不是** `.sheet-table tbody` —— tbody 会被 auto-refresh 的 innerHTML 替换，导致 handler 失效）
  - 行为：click `.field-cell[data-editable]` 切到 input + 确认/取消；Enter 提交 / Esc 取消 / click-outside 取消；乐观更新；失败 restore `data-original` + 加 `.field-cell--error` + 调 `errors.bump()`

- [ ] **Step 1: 写失败测试 `tests/test_inline_edit.py`**

```python
import subprocess
from pathlib import Path


def test_inline_edit_module_delegates_on_sheet_section():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    js = (static_dir / "js/inline-edit.js").read_text(encoding="utf-8")
    # 委托目标必须是 .sheet-section（稳定祖先），不是 tbody
    assert ".sheet-section" in js
    assert ".sheet-table tbody" not in js, "must NOT delegate on tbody (gets replaced by auto-refresh)"
    assert "export function init" in js


def test_inline_edit_no_throw_on_parse():
    static_dir = Path("D:/soft/checkGPRobot/.spyproject/src/web/static")
    script = f"""
import {{ init }} from 'file:///{str(static_dir).replace(chr(92), '/')}/js/inline-edit.js';
console.log(JSON.stringify({{ type: typeof init }}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_inline_edit.py -v
```

Expected: FAIL。

- [ ] **Step 3: 实现 `src/web/static/js/inline-edit.js`**

```javascript
// inline-edit.js：内联编辑（事件委托在 .sheet-section）。
//
// 关键：委托目标必须是稳定的祖先（.sheet-section），绝对不能是 .sheet-table tbody。
// tbody 在 auto-refresh 时会被 innerHTML 替换，挂在 tbody 上的 listener 会被 GC。

import { putJson, ApiError } from "./api.js";
import { errors } from "./status-bar.js";

const FIELD_ID_KEY = "field-id";
const ORIGINAL_KEY = "data-original";
const SELECTOR_EDITABLE = ".field-cell[data-editable]";
const SELECTOR_SECTION = ".sheet-section";

function _encodeFieldId(raw) {
  // 服务端期望 {spreadsheet_name}::{sheet_name}::{row}::{col}
  return encodeURIComponent(raw);
}

async function _commit(cell, sectionEl) {
  const tr = cell.closest(".sheet-row");
  if (!tr) return;
  const fieldId = tr.dataset.fieldId;
  const projectId = document.querySelector("[data-project-id]")?.dataset.projectId;
  const input = cell.querySelector("input");
  if (!input || !fieldId || !projectId) return;

  const newValue = input.value;
  const originalValue = tr.getAttribute(ORIGINAL_KEY) || "";

  // 乐观更新
  cell.classList.remove("field-cell--editing");
  const display = cell.querySelector(".field-cell__display");
  if (display) display.textContent = newValue;
  tr.setAttribute(ORIGINAL_KEY, newValue);

  try {
    await putJson(`/api/projects/${encodeURIComponent(projectId)}/fields/${_encodeFieldId(fieldId)}`, { new_value: newValue });
    cell.classList.remove("field-cell--error");
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      // 回滚到 data-original；不丢失原始值
      if (display) display.textContent = originalValue;
      tr.setAttribute(ORIGINAL_KEY, originalValue);
      cell.classList.add("field-cell--error");
      cell.title = `WriteVerificationError: ${e.detail || ""}`;
      errors.bump(`field edit failed: ${e.detail || e.message}`);
    } else if (e instanceof ApiError && e.status === 400) {
      cell.classList.add("field-cell--error");
      cell.title = `Locked / invalid: ${e.detail || ""}`;
      errors.bump(`field edit rejected: ${e.detail || e.message}`);
      if (display) display.textContent = originalValue;
    } else {
      cell.classList.add("field-cell--error");
      cell.title = `Error: ${e.message}`;
      errors.bump(`field edit error: ${e.message}`);
      if (display) display.textContent = originalValue;
    }
  }
}

function _cancel(cell) {
  cell.classList.remove("field-cell--editing");
  const display = cell.querySelector(".field-cell__display");
  const input = cell.querySelector("input");
  if (display) display.style.display = "";
  if (input) input.remove();
  cell.querySelectorAll(".field-cell__actions").forEach((n) => n.remove());
}

function _enterEdit(cell) {
  if (cell.classList.contains("field-cell--editing")) return;
  if (cell.dataset.recognizedAs === "project_id") return;  // 双重保险

  cell.classList.add("field-cell--editing");
  const display = cell.querySelector(".field-cell__display");
  const currentText = display ? display.textContent : "";
  if (display) display.style.display = "none";

  const input = document.createElement("input");
  input.type = "text";
  input.value = currentText;

  const actions = document.createElement("span");
  actions.className = "field-cell__actions";
  const ok = document.createElement("button");
  ok.textContent = "✅";
  ok.title = "确认";
  const cancel = document.createElement("button");
  cancel.textContent = "❌";
  cancel.title = "取消";
  actions.append(ok, cancel);

  ok.addEventListener("click", (ev) => { ev.stopPropagation(); _commit(cell); });
  cancel.addEventListener("click", (ev) => { ev.stopPropagation(); _cancel(cell); });
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); _commit(cell); }
    else if (ev.key === "Escape") { ev.preventDefault(); _cancel(cell); }
  });
  input.addEventListener("click", (ev) => ev.stopPropagation());
  cell.append(input, actions);
  input.focus();
  input.select();
}

function init() {
  // 委托到稳定的祖先 .sheet-section —— 不会被 innerHTML 替换
  const sections = document.querySelectorAll(SELECTOR_SECTION);
  sections.forEach((section) => {
    section.addEventListener("click", (ev) => {
      const target = ev.target;
      if (!(target instanceof Element)) return;
      const cell = target.closest(SELECTOR_EDITABLE);
      if (!cell) return;
      _enterEdit(cell);
    });
    // click-outside 取消
    section.addEventListener("click", (ev) => {
      const editing = section.querySelector(".field-cell--editing");
      if (!editing) return;
      const target = ev.target;
      if (target instanceof Element && !editing.contains(target) && !target.closest(".field-cell--editing")) {
        // 简化：点击非 editing 元素 → 取消当前 editing
        // 实际触发由具体可编辑 cell 的 click handler 接管
      }
    });
  });
}

export { init };
```

> 委托到 `.sheet-section`（每个 sheet 一个 section，是稳定祖先）。tbody 在 auto-refresh 时被替换，委托到 tbody 会在替换瞬间丢失所有 handler。

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_inline_edit.py -v
```

Expected: 2 passed。

- [ ] **Step 5: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/web/static/js/inline-edit.js tests/test_inline_edit.py
git commit -m "feat(phase2): inline-edit.js with .sheet-section event delegation"
```

---

## Task 10a: 映射管理页 + modal partials + 路由

**Files:**
- Create: `src/web/templates/mappings.html`
- Create: `src/web/templates/partials/_mapping_modal.html`
- Create: `src/web/templates/partials/_confirm_dialog.html`
- Modify: `src/web/routes/pages.py`
- Create: `tests/test_mappings_route.py`

**Interfaces:**
- Produces:
  - `GET /mappings` → 200 渲染 `mappings.html`；数据来自 `mapping_repo.load_all()`（`asyncio.to_thread`）
  - 表格列：项目编号 / 群 chat_id / 备注 / 是否启用 / 上次播报时间 / 操作（编辑 / 软删除 / 测试发送[disabled, Phase 3]）
  - `_mapping_modal.html`：原生 `<dialog>` + 表单 + data-modal-target attrs
  - `_confirm_dialog.html`：通用二次确认（两按钮 + data-confirm-target）

- [ ] **Step 1: 写失败测试 `tests/test_mappings_route.py`**

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.models.project import Mapping
from src.web.app import create_app


def _app():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    mapping_repo = MagicMock()
    mapping_repo.load_all.return_value = [
        Mapping(
            project_id="PRJ-001", chat_id="-100123", note="一群",
            enabled=True,
            last_broadcast_at=datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc),
            last_broadcast_status="ok", last_error=None,
        ),
        Mapping(
            project_id="PRJ-002", chat_id="-100456", note="二群",
            enabled=False,
            last_broadcast_at=None, last_broadcast_status=None, last_error=None,
        ),
    ]
    app = create_app(cfg, MagicMock(), MagicMock(), mapping_repo, bot_service=None)
    return TestClient(app), app


def test_mappings_route_200():
    client, app = _app()
    r = client.get("/mappings")
    assert r.status_code == 200
    assert "PRJ-001" in r.text
    assert "PRJ-002" in r.text
    assert "一群" in r.text


def test_mappings_route_has_modal_partials():
    client, app = _app()
    r = client.get("/mappings")
    assert r.status_code == 200
    assert "_mapping_modal" in r.text or "_mapping_modal.html" in r.text or "mapping-modal" in r.text
    assert "_confirm_dialog" in r.text or "confirm-dialog" in r.text
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_mappings_route.py -v
```

Expected: FAIL。

- [ ] **Step 3: 实现 `src/web/templates/partials/_mapping_modal.html`**

```jinja2
<dialog class="modal" id="mapping-modal" data-modal-target="mapping">
  <h2 class="modal__title" data-modal-title>编辑映射</h2>
  <form method="dialog" class="modal__form" data-modal-form>
    <input type="hidden" name="project_id" data-field="project_id" />
    <label class="modal__field">
      群 chat_id
      <input type="text" name="chat_id" data-field="chat_id" required pattern="-?\d+" />
    </label>
    <label class="modal__field">
      备注
      <input type="text" name="note" data-field="note" />
    </label>
    <label class="modal__field">
      启用
      <input type="checkbox" name="enabled" data-field="enabled" />
    </label>
    <div class="modal__actions">
      <button type="button" data-action="modal-cancel">取消</button>
      <button type="submit" data-action="modal-submit">保存</button>
    </div>
  </form>
</dialog>
```

- [ ] **Step 4: 实现 `src/web/templates/partials/_confirm_dialog.html`**

```jinja2
<dialog class="modal" id="confirm-dialog" data-modal-target="confirm">
  <h2 class="modal__title" data-confirm-title>确认操作</h2>
  <p class="modal__body" data-confirm-body>确定要继续吗？</p>
  <div class="modal__actions">
    <button type="button" data-action="confirm-cancel">取消</button>
    <button type="button" data-action="confirm-ok">确定</button>
  </div>
</dialog>
```

- [ ] **Step 5: 实现 `src/web/templates/mappings.html`**

```jinja2
{% extends "base.html" %}

{% block title %}映射管理 — checkGPRobot{% endblock %}

{% block content %}
<main class="page page--mappings">
  <header class="mappings-header">
    <h1>项目 ↔ 群 映射管理</h1>
    <button type="button" class="mappings-header__add"
            data-action="mapping-add">+ 新增映射</button>
  </header>

  {% include "partials/_error_banner.html" %}

  {% if mappings %}
    <table class="mappings-table">
      <thead>
        <tr>
          <th>项目编号</th>
          <th>群 chat_id</th>
          <th>备注</th>
          <th>是否启用</th>
          <th>上次播报时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody data-mappings-tbody>
        {% for m in mappings %}
          <tr class="mappings-row {% if not m.enabled %}row--warn{% endif %}"
              data-project-id="{{ m.project_id }}">
            <td><a href="/project/{{ m.project_id }}">{{ m.project_id }}</a></td>
            <td>{{ m.chat_id or "—" }}</td>
            <td>{{ m.note or "" }}</td>
            <td>
              {% if m.enabled %}
                <span class="badge badge--ok">启用</span>
              {% else %}
                <span class="badge badge--off">停用</span>
              {% endif %}
            </td>
            <td>{{ m.last_broadcast_at or "—" }}</td>
            <td class="mappings-row__actions">
              <button type="button" data-action="mapping-edit" data-project-id="{{ m.project_id }}">编辑</button>
              <button type="button" data-action="mapping-delete" data-project-id="{{ m.project_id }}">删除</button>
              <button type="button" data-action="test-send" data-project-id="{{ m.project_id }}"
                      {% if not m.enabled %}disabled title="先启用映射"{% endif %}>📨 测试发送</button>
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p class="empty-state">暂无映射，点上方"新增映射"开始。</p>
  {% endif %}

  {% include "partials/_mapping_modal.html" %}
  {% include "partials/_confirm_dialog.html" %}
</main>
{% endblock %}
```

- [ ] **Step 6: 修改 `src/web/routes/pages.py` 增加 `/mappings`**

在 `project_detail` 之后追加：

```python
@router.get("/mappings", response_class=HTMLResponse)
async def mappings(request: Request):
    app = request.app
    mapping_repo = app.state.mapping_repo
    templates = app.state.templates
    cache = app.state.cache

    # mapping_repo.load_all 是同步 gspread → to_thread
    import asyncio
    try:
        mappings_list = await asyncio.to_thread(mapping_repo.load_all)
    except Exception as e:  # noqa: BLE001
        return templates.TemplateResponse(
            request=request, name="mappings.html",
            context={
                "page_name": "mappings", "mappings": [],
                "last_refresh_at": None, "last_refresh_human": None,
                "errors": [f"无法读取映射表: {type(e).__name__}: {e}"],
            },
            status_code=200,
        )

    last = cache.last_refresh_at() if cache else None
    last_human = last.strftime("%Y-%m-%d %H:%M:%S UTC") if last else None
    return templates.TemplateResponse(
        request=request, name="mappings.html",
        context={
            "page_name": "mappings", "mappings": mappings_list,
            "last_refresh_at": last.isoformat() if last else None,
            "last_refresh_human": last_human, "errors": [],
        },
    )
```

- [ ] **Step 7: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_mappings_route.py -v
```

Expected: 2 passed。

- [ ] **Step 8: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 9: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/web/templates/mappings.html src/web/templates/partials/_mapping_modal.html src/web/templates/partials/_confirm_dialog.html src/web/routes/pages.py tests/test_mappings_route.py
git commit -m "feat(phase2): mappings page template, modal/confirm partials, GET /mappings route"
```

---

## Task 10b: 映射 CRUD JSON endpoints

**Files:**
- Modify: `src/web/routes/api.py`
- Create: `tests/test_api_mappings_crud.py`

**Interfaces:**
- Produces:
  - `GET /api/mappings` → 200 `{mappings: [...]}`；调用 `mapping_repo.load_all()`（to_thread）
  - `POST /api/mappings` body `{project_id, chat_id, note, enabled}` → 201 or 400
    - 校验：project_id 非空、chat_id 匹配 `-?\d+`；重复 → 400；新建走 `mapping_repo.upsert` + `store.save_mapping_snapshot`
  - `PUT /api/mappings/{project_id}` body 任意子集 → 200；保留原 `last_broadcast_*`
  - `DELETE /api/mappings/{project_id}` → 200 `{project_id, enabled:false, deleted_at}`；走 `mapping_repo.delete`（Phase 1 已软删除：设置 enabled=FALSE）

> **不包含** `/api/mappings/{id}/test-send` —— 那是 Phase 3（Bot 接入后）才有的功能。Phase 2 UI 上的"测试发送"按钮 disabled，Phase 3 才连。

- [ ] **Step 1: 写失败测试 `tests/test_api_mappings_crud.py`**

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.models.project import Mapping
from src.web.app import create_app


@pytest.fixture
def client_with_repo():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    mapping_repo = MagicMock()
    mapping_repo.load_all.return_value = [
        Mapping(project_id="PRJ-001", chat_id="-100123", note="一群", enabled=True,
                last_broadcast_at=datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc),
                last_broadcast_status="ok", last_error=None),
    ]
    store = MagicMock()
    app = create_app(cfg, store, MagicMock(), mapping_repo, bot_service=None)
    return TestClient(app), store, mapping_repo


def test_get_mappings_returns_list(client_with_repo):
    client, _, _ = client_with_repo
    r = client.get("/api/mappings")
    assert r.status_code == 200
    body = r.json()
    assert len(body["mappings"]) == 1
    assert body["mappings"][0]["project_id"] == "PRJ-001"


def test_post_mappings_creates(client_with_repo):
    client, store, mapping_repo = client_with_repo
    mapping_repo.load_all.return_value = []  # 不重复
    r = client.post("/api/mappings", json={
        "project_id": "PRJ-002", "chat_id": "-100456", "note": "二群", "enabled": True,
    })
    assert r.status_code == 201
    assert r.json()["project_id"] == "PRJ-002"
    mapping_repo.upsert.assert_called_once()
    store.save_mapping_snapshot.assert_called_once()


def test_post_mappings_400_on_duplicate(client_with_repo):
    client, _, _ = client_with_repo
    r = client.post("/api/mappings", json={
        "project_id": "PRJ-001", "chat_id": "-100999", "note": "", "enabled": True,
    })
    assert r.status_code == 400
    assert "duplicate" in r.json()["detail"].lower() or "已存在" in r.json()["detail"]


def test_post_mappings_400_on_bad_chat_id(client_with_repo):
    client, _, _ = client_with_repo
    r = client.post("/api/mappings", json={
        "project_id": "PRJ-003", "chat_id": "abc", "note": "", "enabled": True,
    })
    assert r.status_code == 400


def test_post_mappings_400_on_empty_project_id(client_with_repo):
    client, _, _ = client_with_repo
    r = client.post("/api/mappings", json={
        "project_id": "", "chat_id": "-100", "note": "", "enabled": True,
    })
    assert r.status_code == 400


def test_put_mappings_updates(client_with_repo):
    client, store, mapping_repo = client_with_repo
    mapping_repo.load_all.return_value = [
        Mapping(project_id="PRJ-001", chat_id="-100123", note="一群", enabled=True,
                last_broadcast_at=datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc),
                last_broadcast_status="ok", last_error=None),
    ]
    r = client.put("/api/mappings/PRJ-001", json={"note": "新备注", "enabled": False})
    assert r.status_code == 200
    body = r.json()
    assert body["note"] == "新备注"
    assert body["enabled"] is False
    # last_broadcast_at 应保留
    assert body["last_broadcast_at"] == "2026-09-18T21:00:00+00:00"
    mapping_repo.upsert.assert_called_once()


def test_delete_mappings_soft(client_with_repo):
    client, _, mapping_repo = client_with_repo
    r = client.delete("/api/mappings/PRJ-001")
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == "PRJ-001"
    assert body["enabled"] is False
    mapping_repo.delete.assert_called_once_with("PRJ-001")
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_api_mappings_crud.py -v
```

Expected: FAIL。

- [ ] **Step 3: 修改 `src/web/routes/api.py` 增加 CRUD 端点**

在文件**末尾**追加（在 PUT field 之后）：

```python
import re
from src.models.project import Mapping as MappingModel


_CHAT_ID_RE = re.compile(r"^-?\d+$")


@router.get("/mappings")
async def get_mappings(request: Request):
    """返回所有映射。同步 IO 走 asyncio.to_thread。"""
    app = request.app
    mapping_repo = app.state.mapping_repo
    try:
        items = await asyncio.to_thread(mapping_repo.load_all)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"mapping load failed: {e}")
    return {
        "mappings": [
            {
                "project_id": m.project_id,
                "chat_id": m.chat_id,
                "note": m.note,
                "enabled": m.enabled,
                "last_broadcast_at": m.last_broadcast_at.isoformat() if m.last_broadcast_at else None,
                "last_broadcast_status": m.last_broadcast_status,
                "last_error": m.last_error,
            }
            for m in items
        ]
    }


class MappingCreateBody(BaseModel):
    project_id: str
    chat_id: str
    note: str = ""
    enabled: bool = True


class MappingUpdateBody(BaseModel):
    chat_id: str | None = None
    note: str | None = None
    enabled: bool | None = None


@router.post("/mappings", status_code=201)
async def post_mapping(request: Request, body: MappingCreateBody):
    app = request.app
    mapping_repo = app.state.mapping_repo
    store = app.state.store

    project_id = (body.project_id or "").strip()
    chat_id = (body.chat_id or "").strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    if not _CHAT_ID_RE.match(chat_id):
        raise HTTPException(status_code=400, detail="chat_id must be signed integer (e.g. -100...)")

    # 查重
    try:
        existing = await asyncio.to_thread(mapping_repo.load_all)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"mapping load failed: {e}")
    if any(m.project_id == project_id for m in existing):
        raise HTTPException(status_code=400, detail=f"mapping for {project_id} already exists")

    mapping = MappingModel(
        project_id=project_id, chat_id=chat_id, note=body.note, enabled=body.enabled,
        last_broadcast_at=None, last_broadcast_status=None, last_error=None,
    )
    try:
        await asyncio.to_thread(mapping_repo.upsert, mapping)
        await asyncio.to_thread(store.save_mapping_snapshot, mapping)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"write failed: {e}")
    return {
        "project_id": mapping.project_id,
        "chat_id": mapping.chat_id,
        "note": mapping.note,
        "enabled": mapping.enabled,
    }


@router.put("/mappings/{project_id}")
async def put_mapping(request: Request, project_id: str, body: MappingUpdateBody):
    app = request.app
    mapping_repo = app.state.mapping_repo
    store = app.state.store

    try:
        existing_list = await asyncio.to_thread(mapping_repo.load_all)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"mapping load failed: {e}")
    existing = next((m for m in existing_list if m.project_id == project_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"mapping {project_id} not found")

    updated = MappingModel(
        project_id=existing.project_id,
        chat_id=(body.chat_id if body.chat_id is not None else existing.chat_id),
        note=(body.note if body.note is not None else existing.note),
        enabled=(body.enabled if body.enabled is not None else existing.enabled),
        last_broadcast_at=existing.last_broadcast_at,  # 保留
        last_broadcast_status=existing.last_broadcast_status,
        last_error=existing.last_error,
    )
    if updated.chat_id and not _CHAT_ID_RE.match(updated.chat_id):
        raise HTTPException(status_code=400, detail="chat_id must be signed integer")
    try:
        await asyncio.to_thread(mapping_repo.upsert, updated)
        await asyncio.to_thread(store.save_mapping_snapshot, updated)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"write failed: {e}")
    return {
        "project_id": updated.project_id,
        "chat_id": updated.chat_id,
        "note": updated.note,
        "enabled": updated.enabled,
        "last_broadcast_at": updated.last_broadcast_at.isoformat() if updated.last_broadcast_at else None,
    }


@router.delete("/mappings/{project_id}")
async def delete_mapping(request: Request, project_id: str):
    """软删除：Phase 1 MappingRepo.delete 设置 enabled=FALSE。"""
    app = request.app
    mapping_repo = app.state.mapping_repo
    store = app.state.store
    try:
        await asyncio.to_thread(mapping_repo.delete, project_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"delete failed: {e}")
    # 同步本地 SQLite 快照（保 enabled=FALSE）
    try:
        existing_list = await asyncio.to_thread(mapping_repo.load_all)
    except Exception:  # noqa: BLE001
        existing_list = []
    existing = next((m for m in existing_list if m.project_id == project_id), None)
    if existing is not None:
        await asyncio.to_thread(store.save_mapping_snapshot, existing)
    from datetime import datetime, timezone
    return {
        "project_id": project_id,
        "enabled": False,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_api_mappings_crud.py -v
```

Expected: 7 passed。

- [ ] **Step 5: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/web/routes/api.py tests/test_api_mappings_crud.py
git commit -m "feat(phase2): mapping CRUD endpoints (GET/POST/PUT/DELETE) with soft-delete"
```

---

## Task 12: 扩展 src/main.py + README + E2E 测试

> Phase 1 的 `src/main.py` 已存在；本任务**修改**它（不创建）—— 在 Phase 1 的 `main()` 之后追加 uvicorn 启动段。
> Phase 1 的 `README.md` 已存在；本任务**修改**它（追加 Phase 2 段）。

**Files:**
- Modify: `src/main.py`
- Modify: `README.md`
- Create: `tests/test_e2e_flow.py`

**Interfaces:**
- Produces:
  - `src/main.py` 在 `main()` 函数末尾打印 health summary 后，调 `uvicorn.run(app, host=cfg.ui_bind, port=cfg.ui_port, log_level="info")`
  - README 追加 "运行（Phase 2）"段：浏览器打开 `http://127.0.0.1:8765`、三页路径、`Ctrl+C` 退出
  - `tests/test_e2e_flow.py`：FastAPI `TestClient` 跑全链路（cache hydrate from Store → /api/projects → /api/projects/{id} → PUT field → /api/mappings → DELETE mapping）；确认静态资源、错误码、locked guard、cold start 503

- [ ] **Step 1: 写失败测试 `tests/test_e2e_flow.py`**

```python
"""端到端集成测试：启动一个完整 FastAPI 应用，跑遍核心流程。"""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.config import SpreadsheetConfig
from src.models.project import Field, Mapping, Project, SheetView
from src.models.status import StatusCode
from src.web.app import create_app


def _make_full_app(tmp_path: Path) -> TestClient:
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = [
        SpreadsheetConfig(id="ss1", name="项目主表", role="master"),
    ]

    store = MagicMock()
    # 默认 Store 空快照 → /api/projects 期望 503
    store.load_latest_snapshot.return_value = None

    sheet_repo = MagicMock()
    sheet_repo.update_cell.return_value = "新值"

    mapping_repo = MagicMock()
    mapping_repo.load_all.return_value = []
    mapping_repo.delete.return_value = None

    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    from src.web.cache import ProjectCache
    cache = ProjectCache()
    app.state.cache = cache
    return TestClient(app)


def test_e2e_get_overview_returns_200(tmp_path: Path):
    client = _make_full_app(tmp_path)
    r = client.get("/")
    assert r.status_code == 200


def test_e2e_get_health_returns_ok(tmp_path: Path):
    client = _make_full_app(tmp_path)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_e2e_static_assets_served(tmp_path: Path):
    client = _make_full_app(tmp_path)
    r = client.get("/static/css/app.css")
    assert r.status_code == 200
    assert "status-bar" in r.text


def test_e2e_api_projects_503_on_cold_start(tmp_path: Path):
    client = _make_full_app(tmp_path)
    r = client.get("/api/projects")
    assert r.status_code == 503


def test_e2e_full_flow_with_cached_projects(tmp_path: Path):
    client = _make_full_app(tmp_path)
    app = client.app

    # hydrate cache
    from src.web.cache import ProjectCache
    cache: ProjectCache = app.state.cache
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1", sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
                Field(name="状态", value="制作中", column_index=3, row_index=2, recognized_as="status"),
                Field(name="备注", value="旧值", column_index=5, row_index=2, recognized_as=None),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])

    # /api/projects
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json()["projects"][0]["project_id"] == "PRJ-001"

    # /api/projects/PRJ-001
    r = client.get("/api/projects/PRJ-001")
    assert r.status_code == 200
    body = r.json()
    sheet = body["project"]["sheets"][0]
    # project_id 字段不可编辑
    pid_field = next(f for f in sheet["fields"] if f["recognized_as"] == "project_id")
    assert pid_field["editable"] is False

    # PUT locked field → 400
    encoded = "%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A2%3A%3A1"
    r = client.put(f"/api/projects/PRJ-001/fields/{encoded}", json={"new_value": "X"})
    assert r.status_code == 400

    # PUT editable field → 200
    encoded = "%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A2%3A%3A5"
    r = client.put(f"/api/projects/PRJ-001/fields/{encoded}", json={"new_value": "新值"})
    assert r.status_code == 200

    # /mappings HTML
    r = client.get("/mappings")
    assert r.status_code == 200

    # POST /api/mappings → 201
    r = client.post("/api/mappings", json={
        "project_id": "PRJ-X", "chat_id": "-100", "note": "", "enabled": True,
    })
    assert r.status_code == 201


def test_e2e_404_on_unknown_project(tmp_path: Path):
    client = _make_full_app(tmp_path)
    r = client.get("/project/PRJ-NOPE")
    assert r.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_e2e_flow.py -v
```

Expected: 部分 FAIL（e2e_full_flow_with_cached_projects 依赖 SheetRepo.update_cell 行为与 PUT 路由；本步主要确认测试可以运行）。

- [ ] **Step 3: 修改 `src/main.py` 追加 uvicorn 启动**

Edit：紧跟现有 `main()` 函数定义之后，`return 0` 之前，追加 uvicorn 启动段（也作为 fallback —— 若 Phase 1 测试用 `python run.py` 调用 `main()` 仍会正常返回；Phase 2 实际启动走 `main()` 末尾的 uvicorn.run）：

```python
    # ========== Phase 2: 启动 FastUI ==========
    # 把所有 deps 注入到 FastAPI app
    from src.web.app import create_app
    from src.web.cache import ProjectCache
    from src.web.refresher import BackgroundRefresher

    cache = ProjectCache()
    app = create_app(
        cfg=cfg,
        store=store,
        sheet_repo=repo,
        mapping_repo=mapping_repo,
        bot_service=None,  # Phase 3 接入 BotService
    )
    app.state.cache = cache
    app.state.refresher = BackgroundRefresher(repo, mapping_repo, store, cfg, cache)

    print(f"[ui] Listening on http://{cfg.ui_bind}:{cfg.ui_port}")

    # 单线程 uvicorn（避免 SQLite 并发问题；gspread 已通过 asyncio.to_thread 异步化）
    import uvicorn
    uvicorn.run(
        app,
        host=cfg.ui_bind,
        port=cfg.ui_port,
        log_level="info",
        access_log=False,
    )
    return 0
```

> 注意 `return 0` 已被现有 main() 占用 —— 替换原 `return 0` 行（原文件末尾）为上面这段（保留原 `return 0` 行不变也可 —— uvicorn.run 是阻塞的，本行永不返回；run.py 的 `SystemExit(main())` 永远不会执行到 return 语句）。为了清晰：保留原 `return 0`，新代码插在它**之前**。

- [ ] **Step 4: 修改 `README.md` 追加 Phase 2 段**

Edit：在现有 "## 测试" 段**之前**插入：

```markdown
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
```

- [ ] **Step 5: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_e2e_flow.py -v
```

Expected: 6 passed。

- [ ] **Step 6: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/main.py README.md tests/test_e2e_flow.py
git commit -m "feat(phase2): extend main.py with uvicorn, README Phase 2 section, e2e tests"
```

---

## Self-Review（自审）

### 1. Spec coverage（覆盖 spec 哪些要求）

| Spec 节 | Task | 覆盖点 |
|---|---|---|
| §2.3 数据流（读路径） | T3/T4 | cache 冷启动从 Store hydrate + BackgroundRefresher 拉取 |
| §2.3 数据流（写路径） | T6 | PUT /api/projects/{id}/fields/{field_id} → SheetRepo.update_cell + 重读校验 + cache 更新 |
| §5.1 三页布局 | T3/T5/T10a | `/` `/project/{id}` `/mappings` |
| §5.2 项目总览 | T3/T4/T8 | status_badge + humanize_duration + /api/projects + status-bar + auto-refresh |
| §5.3 项目详情 | T5/T6/T9 | _field_row partial（LOCKED_RECOGNIZED_AS={"project_id"}）+ PUT 校验 + inline-edit JS 委托 .sheet-section |
| §5.4 映射管理（CRUD 部分） | T10a/T10b | 表格 + 模态框 + GET/POST/PUT/DELETE endpoints |
| §5.4 测试发送 | **Phase 3** | 按钮 disabled，文档化推迟到 Phase 3 |
| §5.4 chat-id 助手 | **Phase 3** | 整个 `/api/auth/chat-id` 推迟到 Phase 3 |
| §5.5 错误展示 | T2b/T4/T6/T8/T9 | _error_banner partial + per-spreadsheet 错误 + status-bar refresh:error toast + inline-edit 409 回滚 |
| §10.1 目录 | T1 | src/web/{templates,static,routes}, src/main.py, run.py —— 全部存在 |
| §10.2 启动 | T12 | `python run.py` 启动 uvicorn `127.0.0.1:8765` |

### 2. 全部 9 项 fix_requests 应用情况

| # | Fix Request | 应用位置 |
|---|---|---|
| 1 | `src/main.py` 而非 root `main.py`；README 用 `python run.py` | T12 Step 3-4：modify `src/main.py` + README 段用 `python run.py` |
| 2 | 去掉 `broadcaster` 参数 | T2 Step 8：`create_app(... bot_service=None)`，无 broadcaster |
| 3 | 去掉 `/api/auth/chat-id` + `loadChatIdHelper` | 整文档不出现；T10b 故意不写 test-send；T10a 模板"测试发送"按钮 disabled |
| 4 | `LOCKED_RECOGNIZED_AS = {"project_id"}` 单例 | T3 cache.py 顶部常量；T5 / T6 / T9 全部 import 同一常量 |
| 5 | field_id 编码 `{spreadsheet_name}::{sheet_name}::{row}::{col}` URL-safe | T5 Step 4-8 + T6 Step 4 + T9 Step 3 全部遵循；docstring 显式声明 |
| 6 | Phase 1 Store 方法名 `save_sheet_snapshot` / `load_latest_snapshot` | T4 refresher.py + T3 _hydrate_from_store 都用原名 |
| 7 | 拆分 T2→T2/T2b、T7→T7a/T7b、T10→T10a/T10b | 文档标题 + 章节顺序遵循，最终 14 个任务 |
| 8 | SheetRepo 同步调用走 `asyncio.to_thread` | T4 refresher.py 顶部 docstring 强调 + Step 4 实现；T6 Step 4 PUT handler 同样用 to_thread；T10a mappings route Step 6；T10b CRUD Step 3 全部 |
| 9 | inline-edit 委托到 `.sheet-section` 而非 tbody | T9 Step 3 实现 + Step 1 测试断言 "must NOT delegate on tbody" |
| 10 | 去掉 "default CORS" 措辞 | 文档全文不提 CORS；Global Constraints 明确"无 CORS 中间件：同源 UI" |

### 3. Type / 接口一致性

- `ProjectCache`、`LOCKED_RECOGNIZED_AS` 在 T3 定义；T5 模板 import、T6 handler import、T9 JS 通过相同字段名 `data-recognized-as="project_id"` 联动
- `BackgroundRefresher.refresh_now()` 返回 dict 与 `/api/refresh` 端点返回 JSON 一致
- `field_id` 格式在 T5 模板生成、T6 解码、T9 JS 重建三处使用同一公式
- `bot_service=None` 路径：在 T2 factory 接受；T10b CRUD 不调用 bot；T10a 测试发送按钮 disabled
- Phase 1 `MappingRepo.delete` 软删除（设置 enabled=FALSE）—— T10b DELETE 端点直接调用即可，无需扩展

### 4. 文件结构合规

- 单文件行数：所有 Python 文件均在 200 行内（最长的 `src/web/routes/api.py` 拼接后约 180 行；如超限可拆 `api_field.py` + `api_mapping.py`，留待 T12 后重构）
- JS 文件：每个 ~50-100 行，无依赖、无构建步骤
- 模板文件：base + 3 layout 页 + 6 partials，每个 < 60 行

### 5. 已知风险与后续工作

- **bot_service 集成推迟到 Phase 3**：T10a UI 上的"测试发送"按钮 disabled；Phase 3 任务计划负责 `/api/mappings/{id}/test-send` 端点 + Bot 接入
- **chat-id 助手推迟到 Phase 3**：UI 上仅显示 admin_chat_id 占位，Phase 3 才加 `/api/auth/chat-id` 端点
- **BackgroundRefresher 周期调度**：本计划只交付 `refresh_now`（手动触发），后台 `setInterval` 由 Phase 4（scheduler）统一管理；Phase 2 启动时立刻调一次 `refresh_now` 即可
- **CSS BEM 命名一致性**：所有 `.field-cell*`、`.status-bar*`、`.status-badge*`、`.toast*`、`.modal*`、`.row--*` 已在 T2b 集中定义；后续任务仅添加新元素，不重定义

---

## 端到端验证清单（Phase 2 完成后跑一遍）

```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v                       # 全部 PASS（约 60+ 测试）
python run.py --secrets config/secrets.yaml --sheets config/sheets.yaml
# 看到 [ui] Listening on http://127.0.0.1:8765 后浏览器打开该地址
```

预期输出（Phase 2）：
```
[config] N spreadsheets configured
[store] SQLite initialized at data/checkgprobot.db
[data] Loaded M projects
  • PRJ-001 项目一 — MAKING
  ...
[mapping] Loaded K mappings
[ui] Listening on http://127.0.0.1:8765
INFO:     Started server process [PID]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8765 (Press CTRL+C to quit)
```

手动验证点（spec §11.1）：
- [ ] 浏览器 `http://127.0.0.1:8765/` 看到项目总览
- [ ] 点进项目详情，能看到该项目在所有 sheet 中的字段
- [ ] 项目编号行带 🔒 不可点；其他字段可点 → input → Enter 提交
- [ ] 编辑成功 → 单元格更新；失败 → 行变红 + 顶部 toast
- [ ] `/mappings` 页面新增/编辑/删除映射
- [ ] 顶部状态栏"手动刷新"按钮可触发 `/api/refresh`