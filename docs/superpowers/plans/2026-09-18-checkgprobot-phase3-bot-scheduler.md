# checkGPRobot Phase 3 — Telegram Bot 与定时播报 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Phase 1 数据层 + Phase 2 FastUI 之上交付 Telegram 机器人（命令处理 + 测试发送）与 APScheduler 定时播报（中文 Markdown 文案 + 工作日过滤 + skip_if_no_change + 指数退避重试 + 管理员告警）。UI `/api/mappings/{id}/test-send` 由 deferred 变 active。

**Architecture:** 单进程扩展 —— `src/bot/` 新增 `service.py`（python-telegram-bot asyncio 包装）、`commands.py`（`/status`、`/projects`、`/help`、`/force_broadcast`、`/reload`、`/dryrun`）、`templates.py`（播报文案）、`broadcast.py`（`BroadcastSvc` 全员播报 + 重试）、`notifications.py`（管理员告警）；`src/scheduler/` 新增 `jobs.py` + `config.py`（APScheduler `AsyncIOScheduler` + cron 加载 + 工作日过滤）。FastAPI lifespan context manager 在启动时 `BotService.start(token)` + `scheduler.start()`，关闭时 `scheduler.shutdown(wait=False)` + `BotService.stop()`。同步 gspread 调用走 `asyncio.to_thread` 避免阻塞 uvicorn 单线程 loop。

**Tech Stack:**
- Python 3.11+
- python-telegram-bot[asyncio]>=20.7（含 `httpx` 间接依赖，已存在）
- APScheduler>=3.10,<4.0
- pytest 8.x + pytest-asyncio>=1.0
- 复用 Phase 1：gspread 6.x / google-auth 2.x / PyYAML 6.x / SQLite 3
- 复用 Phase 2：FastAPI 0.115+ / uvicorn[standard] 0.30+ / Jinja2 3.1+

**Spec:** [docs/superpowers/specs/2026-09-18-checkgprobot-design.md](docs/superpowers/specs/2026-09-18-checkgprobot-design.md)（§6 Telegram Bot 与定时播报、§7.1 broadcast_log/status_history、§7.2 缓存策略）

**后续 Phases:**
- Phase 4: 异常/告警收敛 + 报表 / 健康检查增强 / 可选 webhook 升级（暂未规划）
- Phase 5: 公网部署 / HTTPS / 多用户隔离（spec 明确不做；YAGNI）

---

## Global Constraints

- Python 3.11+（spec §1.4）
- 单文件行数 ≤ 200 行；超过则拆
- 提交粒度：一个 task 一个 commit，commit message 格式 `feat(phase3): <verb> <thing>`
- 测试文件命名 `test_*.py`，函数命名 `test_*`
- **Async-first**：所有 bot/调度相关代码用 `async def`；同步 gspread（`MappingRepo.load_all`、`SheetRepo.fetch_all`）必须包到 `asyncio.to_thread(...)` 才不阻塞 uvicorn 单线程 loop
- **FastAPI lifespan 启动/关闭**：bot polling 与 scheduler 都通过 `@asynccontextmanager async def lifespan(app): ...` 在 `create_app` 内注册；启动 `await bot_service.start(token)` + `scheduler.start()`，关闭 `scheduler.shutdown(wait=False)` + `await bot_service.stop()`
- **BotService 协议**：`start(token)` / `stop()` / `send_message(chat_id, text)` / `get_chat_id_hint()`；允许在测试中以 `AsyncMock` 实现 `Protocol`
- **管理员权限检查**：所有 admin-only 命令在 handler 入口 `if update.effective_user.id != admin_chat_id: return`（admin_chat_id 是 int）；失败回 "⛔ 需要管理员权限"
- **Telegram API 重试**：失败时 1s / 2s / 4s 指数退避（spec §6.5）；最终失败标记 `mapping.last_error = "❌ 无法发送"`，调用 `notify_admin`
- **bot_service 注入**：`create_app(..., bot_service=None)` 兼容；`bot_service is None` 时 `/api/mappings/{id}/test-send` 返回 503"Telegram bot not configured"
- **bot 命令群私聊中立**：handler 不区分 chat type；`/status`、`/projects`、`/help` 任何 chat 都接受；admin-only 命令按 user id 鉴权
- **调度策略**：`config/scheduler.yaml` 含 `broadcast.times[]`、`broadcast.weekdays_only`、`broadcast.skip_if_no_change`、`broadcast.per_status_thresholds.{STATUS}: N（天）`；不在 yaml 中出现的 status 用默认 14 天阈值
- **skip_if_no_change 判定**（spec §6.3）：当前 `(status_code, status_changed_at)` 与 SQLite `broadcast_log` 中该 `(project_id, chat_id)` 最近一条成功记录完全相同才跳过；任一字段不同 → 播报
- **status_history 写入**：每次成功播报调 `store.record_status(project_id, status_code, status_changed_at)`，避免重复写入同 `(project_id, status_code, detected_at)`（依赖 PK 约束）
- **dryrun 路径**：`BroadcastSvc.broadcast_all(dryrun=True)` 只渲染文案并返回，不调 `bot_service.send_message`、不写 `broadcast_log`
- **`httpx`**：已随 fastapi/uvicorn 间接安装，PTB v20+ 用 httpx 做 HTTP transport；requirements.txt 不显式 pin
- **pytest-asyncio**：从 env-only（`pip install pytest-asyncio` 但不在 requirements.txt）升级为正式依赖

---

## 文件结构（Phase 3 新增）

```
checkGPRobot/
├── requirements.txt                [T1, modify]
├── README.md                       [T11, modify]
├── config/
│   └── scheduler.yaml.example      [T6]
├── src/
│   ├── main.py                     [T8, modify — 注入 BotService + Scheduler 到 lifespan]
│   ├── web/
│   │   ├── app.py                  [T8, modify — lifespan 启停 bot/scheduler]
│   │   └── routes/
│   │       └── api.py              [T9, modify — /test-send 真正调用 bot_service]
│   ├── bot/                        [T1-T7]
│   │   ├── __init__.py             [T1]
│   │   ├── service.py              [T2]
│   │   ├── commands.py             [T3]
│   │   ├── templates.py            [T4]
│   │   ├── broadcast.py            [T5]
│   │   └── notifications.py        [T7]
│   └── scheduler/                  [T6]
│       ├── __init__.py             [T6]
│       ├── config.py               [T6]
│       └── jobs.py                 [T6]
└── tests/
    ├── test_bot_smoke.py                [T1]
    ├── test_bot_service.py              [T2]
    ├── test_bot_commands.py             [T3]
    ├── test_bot_templates.py            [T4]
    ├── test_bot_broadcast.py            [T5]
    ├── test_scheduler_config.py         [T6]
    ├── test_bot_notifications.py        [T7]
    ├── test_lifespan_integration.py     [T8]
    ├── test_api_test_send.py            [T9]
    └── test_e2e_broadcast_flow.py       [T10]
```

---

## Task 1: bot 依赖与 `src/bot/` 骨架

**Files:**
- Modify: `requirements.txt`
- Create: `src/bot/__init__.py`
- Create: `tests/test_bot_smoke.py`

**Interfaces:**
- Consumes: 无
- Produces: `requirements.txt` 多三行；`src.bot` 包可 import；`pytest-asyncio` 装好

- [ ] **Step 1: 修改 `requirements.txt`**

追加三行：

```
python-telegram-bot[asyncio]>=20.7,<21.0
APScheduler>=3.10,<4.0
pytest-asyncio>=1.0,<1.2
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
python-telegram-bot[asyncio]>=20.7,<21.0
APScheduler>=3.10,<4.0
pytest-asyncio>=1.0,<1.2
```

- [ ] **Step 2: 创建 `src/bot/__init__.py`**

```python
"""src.bot 子包：Telegram Bot + 播报服务。

模块清单：
- service.py      BotService：python-telegram-bot Application 包装
- commands.py     /status /projects /help /force_broadcast /reload /dryrun handler
- templates.py    render_broadcast() Markdown 文案
- broadcast.py    BroadcastSvc 全员播报 + 指数退避
- notifications.py notify_admin()
"""
```

- [ ] **Step 3: 安装依赖**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
pip install -r requirements.txt
```

Expected: 安装成功；`import telegram`、`import apscheduler`、`import pytest_asyncio` 均无异常。

- [ ] **Step 4: 写冒烟测试 `tests/test_bot_smoke.py`**

```python
"""bot 子包与新依赖能被 import。"""
import importlib


def test_src_bot_importable():
    mod = importlib.import_module("src.bot")
    assert mod is not None


def test_telegram_imported():
    import telegram
    from telegram.ext import Application  # noqa: F401
    assert hasattr(telegram, "__version__")


def test_apscheduler_imported():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # noqa: F401


def test_pytest_asyncio_imported():
    import pytest_asyncio  # noqa: F401
    assert pytest_asyncio.__version__ >= "1.0"


def test_httpx_imported():
    import httpx  # noqa: F401
```

- [ ] **Step 5: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_bot_smoke.py -v
```

Expected: 5 passed。

- [ ] **Step 6: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add requirements.txt src/bot/__init__.py tests/test_bot_smoke.py
git commit -m "feat(phase3): add python-telegram-bot + APScheduler deps and src/bot/ skeleton"
```

---

## Task 2: BotService — getMe/start/stop/send_message

**Files:**
- Create: `src/bot/service.py`
- Create: `tests/test_bot_service.py`

**Interfaces:**
- Consumes: `telegram.ext.Application`、`telegram.Bot`
- Produces:
  ```python
  # src/bot/service.py
  class BotService:
      def __init__(self) -> None: ...
      async def start(self, token: str) -> None: ...
          # 1) Application.builder().token(token).build()
          # 2) await app.bot.get_me() 验证 token；失败 raise RuntimeError
          # 3) await app.initialize(); await app.start()
          # 4) await app.updater.start_polling()（drop_pending_updates=True）
      async def stop(self) -> None: ...
          # 顺序：updater.stop_polling() → app.stop() → app.shutdown()
      async def send_message(self, chat_id: int | str, text: str) -> None: ...
          # await self._app.bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
          # 让 Telegram API 异常向上抛，调用方负责重试
      async def get_chat_id_hint(self) -> int | None: ...
          # 返回 _last_update_user_id（最近一次任意 update 的 from_user.id），用于 admin 自助查 id
      @property
      def username(self) -> str | None: ...
          # 返回 getMe 拿到的 bot username（@xxx）
  ```

  注意：`BotService` 通过 `self._app: Application` 持有 PTB Application；测试中通过 Protocol/子类化注入 fake。

- [ ] **Step 1: 写失败测试 `tests/test_bot_service.py`**

```python
"""BotService 单元测试：用 AsyncMock 注入假 Application + Bot。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.service import BotService


pytestmark = pytest.mark.asyncio


def _fake_app_and_bot(*, me_username: str = "test_bot"):
    """构造 (Application, Bot) 双子 mock。getMe 返回 User-like 对象。"""
    bot = MagicMock()
    user = MagicMock()
    user.username = me_username
    user.id = 999
    bot.get_me = AsyncMock(return_value=user)
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

    app = MagicMock()
    app.bot = bot
    app.initialize = AsyncMock()
    app.start = AsyncMock()
    app.shutdown = AsyncMock()
    app.stop = AsyncMock()

    updater = MagicMock()
    updater.start_polling = AsyncMock()
    updater.stop_polling = AsyncMock()
    app.updater = updater

    return app, bot


async def test_start_validates_token_via_get_me():
    svc = BotService()
    app, bot = _fake_app_and_bot(me_username="my_bot")
    with patch("src.bot.service.Application") as AppCls:
        builder = MagicMock()
        builder.token.return_value = builder
        builder.build.return_value = app
        AppCls.builder.return_value = builder
        await svc.start("123:ABC")

    bot.get_me.assert_awaited_once()
    app.initialize.assert_awaited_once()
    app.start.assert_awaited_once()
    app.updater.start_polling.assert_awaited_once()
    assert svc.username == "my_bot"


async def test_start_raises_on_invalid_token():
    svc = BotService()
    app, bot = _fake_app_and_bot()
    bot.get_me = AsyncMock(side_effect=RuntimeError("Unauthorized"))
    with patch("src.bot.service.Application") as AppCls:
        builder = MagicMock()
        builder.token.return_value = builder
        builder.build.return_value = app
        AppCls.builder.return_value = builder
        with pytest.raises(RuntimeError, match="Unauthorized"):
            await svc.start("BAD_TOKEN")


async def test_stop_reverses_start_order():
    svc = BotService()
    app, bot = _fake_app_and_bot()
    with patch("src.bot.service.Application") as AppCls:
        builder = MagicMock()
        builder.token.return_value = builder
        builder.build.return_value = app
        AppCls.builder.return_value = builder
        await svc.start("ok")

    await svc.stop()
    app.updater.stop_polling.assert_awaited_once()
    app.stop.assert_awaited_once()
    app.shutdown.assert_awaited_once()


async def test_send_message_calls_bot():
    svc = BotService()
    app, bot = _fake_app_and_bot()
    with patch("src.bot.service.Application") as AppCls:
        builder = MagicMock()
        builder.token.return_value = builder
        builder.build.return_value = app
        AppCls.builder.return_value = builder
        await svc.start("ok")

    await svc.send_message(123456, "hello")
    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 123456
    assert kwargs["text"] == "hello"


async def test_get_chat_id_hint_returns_none_before_any_update():
    svc = BotService()
    assert await svc.get_chat_id_hint() is None


async def test_username_none_before_start():
    svc = BotService()
    assert svc.username is None
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_bot_service.py -v
```

Expected: FAIL（`ModuleNotFoundError: No module named 'src.bot.service'`）。

- [ ] **Step 3: 实现 `src/bot/service.py`**

```python
"""BotService：python-telegram-bot Application 的异步包装。

职责：
- start(token): 构造 Application，调 getMe 验证 token，启动 polling
- stop(): 反向关闭（updater → app → shutdown）
- send_message(chat_id, text): 发送消息；让异常向上抛，由调用方（BroadcastSvc）做重试
- get_chat_id_hint(): 返回最近一次任意 update 的 from_user.id，admin 自助查询用

PTB v20+ 的 Application 是 asyncio.Application，所有 init/start/shutdown 协程化。
"""
from __future__ import annotations

from typing import Optional

from telegram.ext import Application


class BotService:
    def __init__(self) -> None:
        self._app: Optional[Application] = None
        self._bot_username: Optional[str] = None
        self._last_update_user_id: Optional[int] = None

    async def start(self, token: str) -> None:
        """构造 Application、验证 token、启动 polling。

        Raises:
            RuntimeError: getMe 抛异常（token 无效 / 网络问题）
        """
        builder = Application.builder().token(token)
        app = builder.build()
        self._app = app

        me = await app.bot.get_me()
        if me is None or not getattr(me, "username", None):
            raise RuntimeError(f"getMe returned invalid user: {me!r}")
        self._bot_username = me.username

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

    async def stop(self) -> None:
        """关闭顺序：updater → app → shutdown。"""
        if self._app is None:
            return
        try:
            await self._app.updater.stop_polling()
        finally:
            try:
                await self._app.stop()
            finally:
                await self._app.shutdown()
        self._app = None

    async def send_message(self, chat_id: int | str, text: str) -> None:
        """发送 MarkdownV2 消息。Telegram API 异常向上抛。"""
        if self._app is None:
            raise RuntimeError("BotService not started")
        await self._app.bot.send_message(
            chat_id=chat_id, text=text, parse_mode="MarkdownV2"
        )

    async def get_chat_id_hint(self) -> Optional[int]:
        """返回最近一次任意 update 的 from_user.id，供 admin 自助查 chat_id。

        注：本任务仅暴露 getter；具体更新 _last_update_user_id 的逻辑留给 T3
        的 update listener（届时会有一个 no-op handler 写入该字段）。
        当前返回已记录的值或 None。
        """
        return self._last_update_user_id

    @property
    def username(self) -> Optional[str]:
        return self._bot_username
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_bot_service.py -v
```

Expected: 6 passed。

- [ ] **Step 5: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS，无回归。

- [ ] **Step 6: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/bot/service.py tests/test_bot_service.py
git commit -m "feat(phase3): BotService wrapping python-telegram-bot Application"
```

---

## Task 3: 命令处理器 — /status /projects /help /force_broadcast /reload /dryrun

**Files:**
- Create: `src/bot/commands.py`
- Create: `tests/test_bot_commands.py`
- Modify: `src/bot/service.py`

**Interfaces:**
- Consumes: `telegram.Update`、`telegram.ext.CallbackContext`、`ProjectCache`、`BroadcastSvc`、`Store`
- Produces:
  ```python
  # src/bot/commands.py
  def register_handlers(
      app: Application,
      *,
      admin_chat_id: int,
      cache: ProjectCache,
      broadcast_svc: "BroadcastSvc",  # forward ref
      bot_service: BotService,
      store: Store,
  ) -> None:
      """把 6 个 CommandHandler 注册到 app（注意：broadcast_svc 是 Protocol 或 duck-type）"""

  async def status_cmd(update, context) -> None: ...
  async def projects_cmd(update, context) -> None: ...
  async def help_cmd(update, context) -> None: ...
  async def force_broadcast_cmd(update, context) -> None: ...
  async def reload_cmd(update, context) -> None: ...
  async def dryrun_cmd(update, context) -> None: ...

  # 辅助
  def _is_admin(update, admin_chat_id: int) -> bool: ...
  async def _reply(update, text: str) -> None: ...
  ```

- [ ] **Step 1: 写失败测试 `tests/test_bot_commands.py`**

```python
"""bot 命令处理器测试。用 MagicMock 模拟 Update/Context。"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.commands import (
    help_cmd,
    projects_cmd,
    status_cmd,
    force_broadcast_cmd,
    reload_cmd,
    dryrun_cmd,
    register_handlers,
    _is_admin,
)
from src.models.project import Project
from src.models.status import StatusCode
from src.web.cache import ProjectCache


pytestmark = pytest.mark.asyncio


ADMIN_ID = 111


def _make_update(*, user_id: int, text: str | None = None, args: list[str] | None = None):
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat = MagicMock()
    update.effective_chat.id = 999
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.text = text or "/help"
    update.message.text.split = MagicMock(return_value=["/help", *(args or [])])
    return update


def _make_context(args: list[str] | None = None):
    ctx = MagicMock()
    ctx.args = args or []
    return ctx


# ---------- _is_admin ----------

def test_is_admin_true_when_match():
    u = _make_update(user_id=ADMIN_ID)
    assert _is_admin(u, ADMIN_ID) is True


def test_is_admin_false_when_mismatch():
    u = _make_update(user_id=42)
    assert _is_admin(u, ADMIN_ID) is False


# ---------- /help ----------

async def test_help_cmd_replies_with_command_list():
    u = _make_update(user_id=42)
    c = _make_context()
    await help_cmd(u, c)
    u.message.reply_text.assert_awaited_once()
    text = u.message.reply_text.await_args.args[0]
    assert "/status" in text
    assert "/projects" in text
    assert "/help" in text
    assert "/force_broadcast" in text
    assert "/reload" in text
    assert "/dryrun" in text


# ---------- /status ----------

async def test_status_cmd_with_known_project():
    cache = ProjectCache()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[],
    )
    cache.replace([p])
    u = _make_update(user_id=42, args=["PRJ-001"])
    c = _make_context(args=["PRJ-001"])
    c.bot_data = {"cache": cache}
    # PTB 把 context.bot_data 暴露为 ContextTypes 属性；我们用 bot_data dict
    # status_cmd 通过 context.bot_data["cache"] 读取
    await status_cmd(u, c)
    u.message.reply_text.assert_awaited_once()
    text = u.message.reply_text.await_args.args[0]
    assert "PRJ-001" in text
    assert "MAKING" in text or "我方制作中" in text


async def test_status_cmd_with_unknown_project():
    cache = ProjectCache()
    cache.replace([])
    u = _make_update(user_id=42, args=["PRJ-NOPE"])
    c = _make_context(args=["PRJ-NOPE"])
    c.bot_data = {"cache": cache}
    await status_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "未找到" in text or "not found" in text.lower()


async def test_status_cmd_without_args_prompts():
    cache = ProjectCache()
    u = _make_update(user_id=42, args=[])
    c = _make_context(args=[])
    c.bot_data = {"cache": cache}
    await status_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "/status" in text or "项目编号" in text


# ---------- /projects ----------

async def test_projects_cmd_lists_all():
    cache = ProjectCache()
    p1 = Project(project_id="PRJ-001", project_name="项目一",
                 status=StatusCode.MAKING, status_changed_at=None, sheets=[])
    p2 = Project(project_id="PRJ-002", project_name=None,
                 status=StatusCode.PUBLISHED, status_changed_at=None, sheets=[])
    cache.replace([p1, p2])
    u = _make_update(user_id=42)
    c = _make_context()
    c.bot_data = {"cache": cache}
    await projects_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "PRJ-001" in text
    assert "PRJ-002" in text


# ---------- admin gates ----------

async def test_force_broadcast_rejects_non_admin():
    u = _make_update(user_id=42)
    c = _make_context()
    c.bot_data = {"admin_chat_id": ADMIN_ID, "broadcast_svc": MagicMock(broadcast_all=AsyncMock())}
    await force_broadcast_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "管理员" in text or "⛔" in text


async def test_force_broadcast_runs_for_admin():
    svc = MagicMock()
    svc.broadcast_all = AsyncMock(return_value={"sent": 1, "skipped": 0, "failed": 0})
    u = _make_update(user_id=ADMIN_ID)
    c = _make_context()
    c.bot_data = {"admin_chat_id": ADMIN_ID, "broadcast_svc": svc}
    await force_broadcast_cmd(u, c)
    svc.broadcast_all.assert_awaited_once()
    text = u.message.reply_text.await_args.args[0]
    assert "完成" in text or "✅" in text


async def test_reload_rejects_non_admin():
    u = _make_update(user_id=42)
    c = _make_context()
    c.bot_data = {"admin_chat_id": ADMIN_ID, "store": MagicMock(),
                  "mapping_repo": MagicMock(), "cache": ProjectCache()}
    await reload_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "管理员" in text or "⛔" in text


async def test_dryrun_returns_rendered_text_without_sending():
    svc = MagicMock()
    svc.broadcast_all = AsyncMock(return_value={
        "sent": 0, "skipped": 0, "failed": 0, "dryrun": True, "preview": "📊 PRJ-001"
    })
    u = _make_update(user_id=ADMIN_ID)
    c = _make_context()
    c.bot_data = {"admin_chat_id": ADMIN_ID, "broadcast_svc": svc}
    await dryrun_cmd(u, c)
    svc.broadcast_all.assert_awaited_once()
    call = svc.broadcast_all.await_args
    assert call.kwargs.get("dryrun") is True


# ---------- register_handlers ----------

async def test_register_handlers_registers_six():
    app = MagicMock()
    app.add_handler = MagicMock()
    cache = ProjectCache()
    register_handlers(
        app, admin_chat_id=ADMIN_ID, cache=cache,
        broadcast_svc=MagicMock(), bot_service=MagicMock(), store=MagicMock(),
    )
    # 6 CommandHandler + 1 监听 user_id 的 MessageHandler（hint）= 至少 6 次
    assert app.add_handler.call_count >= 6
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_bot_commands.py -v
```

Expected: FAIL（`ModuleNotFoundError: No module named 'src.bot.commands'`）。

- [ ] **Step 3: 实现 `src/bot/commands.py`**

```python
"""Telegram bot 命令处理。

- /status [PRJ-XXX]        所有人
- /projects                所有人
- /help                    所有人
- /force_broadcast         admin only
- /reload                  admin only
- /dryrun                  admin only

依赖通过 context.bot_data 注入：
  cache, store, mapping_repo, broadcast_svc, admin_chat_id, bot_service

注册：register_handlers(app, ...) 由 lifespan 在 start polling 之前调用。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from src.web.cache import ProjectCache

if TYPE_CHECKING:
    from src.bot.service import BotService
    from src.bot.broadcast import BroadcastSvc


HELP_TEXT = (
    "🤖 *checkGPRobot*\n\n"
    "/status PRJ-XXX — 查看项目当前状态\n"
    "/projects — 列出所有项目\n"
    "/help — 帮助\n"
    "/force\\_broadcast — 立即全员播报（管理员）\n"
    "/reload — 重读所有配置（管理员）\n"
    "/dryrun — 渲染文案预览，不发送（管理员）"
)


def _is_admin(update: Update, admin_chat_id: int) -> bool:
    user = update.effective_user
    return user is not None and user.id == admin_chat_id


async def _reply(update: Update, text: str) -> None:
    await update.message.reply_text(text, parse_mode="MarkdownV2")


# ---------- handlers ----------

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    cache: ProjectCache = context.bot_data["cache"]
    if not args:
        await _reply(update, "用法: `/status PRJ-XXX`")
        return
    pid = args[0]
    p = cache.get(pid)
    if p is None:
        await _reply(update, f"❓ 未找到项目 `{pid}`")
        return
    from src.web.filters import humanize_duration

    dwell = 0
    if p.status_changed_at:
        from datetime import datetime, timezone
        dwell = max(0, int((datetime.now(timezone.utc) - p.status_changed_at).total_seconds()))
    status_text = p.status.value if p.status else "未知"
    name_text = p.project_name or "（未命名）"
    await _reply(
        update,
        f"📊 *{p.project_id} {name_text}*\n"
        f"▸ 当前状态：`{status_text}`\n"
        f"▸ 停留时长：`{humanize_duration(dwell)}`",
    )


async def projects_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cache: ProjectCache = context.bot_data["cache"]
    summaries = cache.list_summaries()
    if not summaries:
        await _reply(update, "暂无项目。")
        return
    lines = ["📋 *所有项目*"]
    for s in summaries:
        status_text = s.status.value if s.status else "未知"
        lines.append(f"• `{s.project_id}` — `{status_text}`")
    await _reply(update, "\n".join(lines))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, HELP_TEXT)


async def force_broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = context.bot_data["admin_chat_id"]
    if not _is_admin(update, admin_id):
        await _reply(update, "⛔ 需要管理员权限。")
        return
    svc = context.bot_data["broadcast_svc"]
    result = await svc.broadcast_all(skip_if_no_change=True, dryrun=False)
    await _reply(
        update,
        f"✅ 播报完成: sent={result.get('sent', 0)} skipped={result.get('skipped', 0)} "
        f"failed={result.get('failed', 0)}",
    )


async def reload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = context.bot_data["admin_chat_id"]
    if not _is_admin(update, admin_id):
        await _reply(update, "⛔ 需要管理员权限。")
        return
    store = context.bot_data["store"]
    mapping_repo = context.bot_data["mapping_repo"]
    # load_all 是同步 gspread；包 to_thread
    import asyncio
    try:
        mappings = await asyncio.to_thread(mapping_repo.load_all)
    except Exception as e:  # noqa: BLE001
        await _reply(update, f"⚠ 重读失败: `{type(e).__name__}: {e}`")
        return
    for m in mappings:
        await asyncio.to_thread(store.save_mapping_snapshot, m)
    await _reply(update, f"🔄 已重读 {len(mappings)} 条映射。")


async def dryrun_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = context.bot_data["admin_chat_id"]
    if not _is_admin(update, admin_id):
        await _reply(update, "⛔ 需要管理员权限。")
        return
    svc = context.bot_data["broadcast_svc"]
    result = await svc.broadcast_all(skip_if_no_change=True, dryrun=True)
    preview = result.get("preview", "（无预览）")
    await _reply(update, f"🧪 *Dryrun 预览*\n```\n{preview}\n```")


# ---------- user_id 监听（hint 给 admin 用） ----------

async def _record_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """每条消息触发：把 from_user.id 存进 bot_data，供 admin 用 /help 时回显。"""
    bot_service: "BotService" = context.bot_data.get("bot_service")
    user = update.effective_user
    if bot_service is not None and user is not None:
        bot_service._last_update_user_id = user.id  # noqa: SLF001
    # 不回消息，避免打扰


def register_handlers(
    app: Any,
    *,
    admin_chat_id: int,
    cache: ProjectCache,
    broadcast_svc: "BroadcastSvc",
    bot_service: "BotService",
    store: Any,
) -> None:
    """注册 6 个命令 + 1 个 user_id 监听。"""
    app.bot_data["cache"] = cache
    app.bot_data["broadcast_svc"] = broadcast_svc
    app.bot_data["bot_service"] = bot_service
    app.bot_data["store"] = store
    app.bot_data["admin_chat_id"] = admin_chat_id
    # mapping_repo 由 lifespan 单独挂（reload 用）
    # 这里不直接读 mapping_repo，避免循环 import；lifespan 在 register 前补

    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("projects", projects_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("force_broadcast", force_broadcast_cmd))
    app.add_handler(CommandHandler("reload", reload_cmd))
    app.add_handler(CommandHandler("dryrun", dryrun_cmd))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, _record_user_id))
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_bot_commands.py -v
```

Expected: 14 passed。

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
git add src/bot/commands.py tests/test_bot_commands.py
git commit -m "feat(phase3): bot command handlers with admin permission gate"
```

---

## Task 4: 播报文案模板 `render_broadcast`

**Files:**
- Create: `src/bot/templates.py`
- Create: `tests/test_bot_templates.py`

**Interfaces:**
- Consumes: `Project`、`Mapping`、`datetime`、`bool` (exceeded_threshold)
- Produces:
  ```python
  # src/bot/templates.py
  STATUS_EMOJI: dict[StatusCode, str]  # 🟣/🟠/🟢/🔴 等

  def render_broadcast(
      project: Project,
      mapping: Mapping,
      now: datetime,
      exceeded_threshold: bool,
      *,
      source_sheet_name: str | None = None,
      responsible_person: str | None = None,
  ) -> str: ...
      # Markdown（注意 MarkdownV2 转义），含:
      # - 📊 *PRJ-001 项目一*
      # - 当前状态: emoji + 中文 + dwell_seconds（humanize_duration）
      # - ⚠ 超过阈值
      # - 最近流转: status_history 最后一条（"由 X → Y"）
      # - 责任人
      # - — now.strftime 自动播报

  def render_dryrun_preview(project: Project, mapping: Mapping, now: datetime) -> str: ...
      # 与 render_broadcast 一致但前缀 "[DRYRUN]"
  ```

- [ ] **Step 1: 写失败测试 `tests/test_bot_templates.py`**

```python
"""播报文案模板测试。"""
from datetime import datetime, timezone

from src.bot.templates import render_broadcast, render_dryrun_preview, STATUS_EMOJI
from src.models.project import Mapping, Project
from src.models.status import StatusCode


def _project(**kw):
    base = dict(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        status_history=[(StatusCode.ORDERED, datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc))],
        sheets=[],
    )
    base.update(kw)
    return Project(**base)


def _mapping(**kw):
    base = dict(
        project_id="PRJ-001", chat_id="123456",
        note="", enabled=True,
        last_broadcast_at=None, last_broadcast_status=None, last_error=None,
    )
    base.update(kw)
    return Mapping(**base)


def test_status_emoji_table_covers_common_codes():
    for c in [StatusCode.MAKING, StatusCode.CLIENT_REVIEW, StatusCode.PUBLISHED,
              StatusCode.PAID, StatusCode.FIRST_REVIEW_REJECTED, StatusCode.UNPAID]:
        assert c in STATUS_EMOJI


def test_render_broadcast_basic_shape():
    p = _project()
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False,
                            responsible_person="张三", source_sheet_name="项目主表")
    assert "PRJ-001" in text
    assert "项目一" in text
    assert "MAKING" in text
    assert "张三" in text
    assert "项目主表" in text
    # dwell 9 小时 = 9 小时（09:18 21:00 - 09:18 12:00）
    assert "9 小时" in text
    # footer
    assert "09-18 21:00" in text


def test_render_broadcast_includes_warning_on_threshold():
    p = _project(status=StatusCode.CLIENT_REVIEW,
                 status_changed_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc))
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=True)
    assert "⚠" in text
    assert "CLIENT_REVIEW" in text


def test_render_broadcast_includes_recent_transition():
    p = _project(
        status=StatusCode.CLIENT_REVIEW,
        status_history=[
            (StatusCode.ORDERED, datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)),
            (StatusCode.MAKING, datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)),
            (StatusCode.CLIENT_REVIEW, datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)),
        ],
    )
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False)
    assert "MAKING" in text  # 上一个状态
    assert "CLIENT_REVIEW" in text  # 当前


def test_render_broadcast_handles_missing_name_and_responsible():
    p = _project(project_name=None)
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False)
    assert "PRJ-001" in text
    assert "未命名" in text or "—" in text


def test_render_dryrun_preview_has_dryrun_prefix():
    p = _project()
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_dryrun_preview(p, m, now)
    assert "DRYRUN" in text.upper() or "试运行" in text or "预览" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_bot_templates.py -v
```

Expected: FAIL。

- [ ] **Step 3: 实现 `src/bot/templates.py`**

```python
"""播报 Markdown 文案模板。

render_broadcast() 产出 Telegram Markdown（PTB 客户端会再加 MarkdownV2 转义
的兼容层；这里用 PTB 默认 Markdown 即可，复杂字符如 . _ * 由 PTB 服务端校验）。

spec §6.4 文案示例：

📊 *PRJ-001 项目一*
▸ 当前状态：🟣 对方验收中（已停留 2 天 3 小时）
▸ 最近流转：09-16 18:00 由 `我方制作中` → `对方验收中`
▸ 责任人：张三（来自表"项目主表"）

— 09-18 21:00 自动播报

异常播报前缀 + ⚠ 超过阈值。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.models.project import Mapping, Project
from src.models.status import StatusCode
from src.web.filters import humanize_duration


STATUS_EMOJI: dict[StatusCode, str] = {
    StatusCode.ORDERED: "🔵",
    StatusCode.MAKING: "🟣",
    StatusCode.CLIENT_REVIEW: "🟠",
    StatusCode.REWORK: "🟠",
    StatusCode.WAITING_AAB: "🟡",
    StatusCode.WAITING_SUBMIT: "🟡",
    StatusCode.SUBMITTING: "🟡",
    StatusCode.FIRST_REVIEW_PASSED: "🟡",
    StatusCode.FIRST_REVIEW_REJECTED: "🔴",
    StatusCode.SECOND_REVIEW: "🟡",
    StatusCode.REMAKING: "🟠",
    StatusCode.PUBLISHED: "🟢",
    StatusCode.PAID: "🟢",
    StatusCode.UNPAID: "🔴",
}

STATUS_DISPLAY_CN: dict[StatusCode, str] = {
    StatusCode.ORDERED: "对方下单",
    StatusCode.MAKING: "我方制作中",
    StatusCode.CLIENT_REVIEW: "对方验收中",
    StatusCode.REWORK: "返工中",
    StatusCode.WAITING_AAB: "等待AAB包",
    StatusCode.WAITING_SUBMIT: "等待提审",
    StatusCode.SUBMITTING: "提审中",
    StatusCode.FIRST_REVIEW_PASSED: "一审通过",
    StatusCode.FIRST_REVIEW_REJECTED: "一审打回",
    StatusCode.SECOND_REVIEW: "复审中",
    StatusCode.REMAKING: "我方重做中",
    StatusCode.PUBLISHED: "已发布",
    StatusCode.PAID: "对方已回款",
    StatusCode.UNPAID: "对方未回款",
}


def _format_status_line(project: Project, now: datetime) -> str:
    if project.status is None:
        return "▸ 当前状态：未知"
    emoji = STATUS_EMOJI.get(project.status, "⚪")
    cn = STATUS_DISPLAY_CN.get(project.status, project.status.value)
    dwell = 0
    if project.status_changed_at:
        dwell = max(0, int((now - project.status_changed_at).total_seconds()))
    return f"▸ 当前状态：{emoji} {cn}（已停留 {humanize_duration(dwell)}）"


def _format_transition_line(project: Project) -> str:
    """最近流转：status_history 最后两条。"""
    hist = list(project.status_history or [])
    if len(hist) < 2:
        return "▸ 最近流转：—"
    prev_code, prev_at = hist[-2]
    curr_code, _ = hist[-1]
    prev_cn = STATUS_DISPLAY_CN.get(prev_code, prev_code.value)
    curr_cn = STATUS_DISPLAY_CN.get(curr_code, curr_code.value)
    return (
        f"▸ 最近流转：{prev_at.strftime('%m-%d %H:%M')} "
        f"由 `{prev_cn}` → `{curr_cn}`"
    )


def _format_responsible_line(
    responsible_person: Optional[str], source_sheet_name: Optional[str]
) -> str:
    if not responsible_person and not source_sheet_name:
        return "▸ 责任人：—"
    if responsible_person and source_sheet_name:
        return f"▸ 责任人：{responsible_person}（来自表「{source_sheet_name}」）"
    return f"▸ 责任人：{responsible_person or '—'}"


def render_broadcast(
    project: Project,
    mapping: Mapping,
    now: datetime,
    exceeded_threshold: bool,
    *,
    responsible_person: Optional[str] = None,
    source_sheet_name: Optional[str] = None,
) -> str:
    name = project.project_name or "（未命名）"
    head = f"📊 *{project.project_id} {name}*"
    if exceeded_threshold:
        head += " ⚠"
    lines = [
        head,
        _format_status_line(project, now),
        _format_transition_line(project),
        _format_responsible_line(responsible_person, source_sheet_name),
        "",
        f"— {now.strftime('%m-%d %H:%M')} 自动播报",
    ]
    return "\n".join(lines)


def render_dryrun_preview(project: Project, mapping: Mapping, now: datetime) -> str:
    body = render_broadcast(project, mapping, now, exceeded_threshold=False)
    return f"🧪 *DRYRUN 预览*\n```\n{body}\n```"
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_bot_templates.py -v
```

Expected: 6 passed。

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
git add src/bot/templates.py tests/test_bot_templates.py
git commit -m "feat(phase3): broadcast Markdown template with threshold warning"
```

---

## Task 5: BroadcastSvc — broadcast_all + 指数退避 + skip_if_no_change

**Files:**
- Create: `src/bot/broadcast.py`
- Create: `tests/test_bot_broadcast.py`

**Interfaces:**
- Consumes: `BotService`、`MappingRepo`、`Store`、`ProjectCache`、`scheduler config (per_status_thresholds)`
- Produces:
  ```python
  # src/bot/broadcast.py
  class BroadcastSvc:
      def __init__(
          self,
          bot_service: BotService,
          mapping_repo: MappingRepo,
          store: Store,
          cache: ProjectCache,
          admin_chat_id: int,
          *,
          per_status_thresholds: dict[str, int] | None = None,  # STATUS -> days
          retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0),
      ) -> None: ...

      async def broadcast_all(
          self,
          skip_if_no_change: bool = True,
          dryrun: bool = False,
      ) -> dict:
          """Returns {"sent": int, "skipped": int, "failed": int, "preview"?: str, "dryrun": bool}"""
  ```

  内部细节：
  - `mapping_repo.load_all()` 同步 → `await asyncio.to_thread(mapping_repo.load_all)`
  - 对每条 `mapping.enabled=True`：
    - `cache.get(mapping.project_id)` 拿 Project
    - 计算 dwell_seconds
    - exceeded_threshold = dwell_days > per_status_thresholds.get(status, 14)
    - 若 skip_if_no_change 且 `store.latest_successful_broadcast(pid, chat_id)` 等于当前 `(status_code, status_changed_at_iso)` → 计入 skipped
    - 渲染文案
    - send：1s / 2s / 4s 重试；全失败 → failed += 1，记录 `mapping.last_error = "❌ 无法发送"`
    - 成功 → `store.log_broadcast(...)`；`store.record_status(pid, status, status_changed_at)`
    - dryrun：只渲染首条 enabled 映射并 return preview
  - 若 any failed > 0 → `await notify_admin(bot_service, admin_chat_id, summary)`（T7 实现）

- [ ] **Step 1: 写失败测试 `tests/test_bot_broadcast.py`**

```python
"""BroadcastSvc 单元测试。BotService / MappingRepo / Store / Cache 全部 fake。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.broadcast import BroadcastSvc
from src.models.project import Mapping, Project
from src.models.status import StatusCode
from src.web.cache import ProjectCache


pytestmark = pytest.mark.asyncio


ADMIN_ID = 42


def _project(pid: str = "PRJ-001", status=StatusCode.MAKING,
             changed_at: datetime | None = None):
    return Project(
        project_id=pid, project_name=f"项目{pid}",
        status=status,
        status_changed_at=changed_at or datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        status_history=[(status, changed_at or datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc))],
        sheets=[],
    )


def _mapping(pid: str = "PRJ-001", chat_id: str = "100",
             enabled: bool = True, **kw):
    base = dict(
        project_id=pid, chat_id=chat_id, note="", enabled=enabled,
        last_broadcast_at=None, last_broadcast_status=None, last_error=None,
    )
    base.update(kw)
    return Mapping(**base)


def _deps(send_message_side_effect=None):
    bot_service = MagicMock()
    bot_service.send_message = AsyncMock(side_effect=send_message_side_effect)

    mapping_repo = MagicMock()
    mapping_repo.load_all = MagicMock(return_value=[_mapping()])

    store = MagicMock()
    store.log_broadcast = MagicMock()
    store.latest_successful_broadcast = MagicMock(return_value=None)
    store.record_status = MagicMock()
    store.save_mapping_snapshot = MagicMock()

    cache = ProjectCache()
    cache.replace([_project()])

    return bot_service, mapping_repo, store, cache


# ---------- happy path ----------

async def test_broadcast_all_sends_one_message_and_logs():
    bot_service, mapping_repo, store, cache = _deps()
    svc = BroadcastSvc(
        bot_service, mapping_repo, store, cache, ADMIN_ID,
        retry_delays=(0, 0, 0),  # 加速测试
    )
    result = await svc.broadcast_all(skip_if_no_change=False, dryrun=False)
    assert result["sent"] == 1
    assert result["skipped"] == 0
    assert result["failed"] == 0
    bot_service.send_message.assert_awaited_once()
    store.log_broadcast.assert_called_once()
    store.record_status.assert_called_once()


# ---------- skip_if_no_change ----------

async def test_skip_if_no_change_when_last_broadcast_matches():
    bot_service, mapping_repo, store, cache = _deps()
    # 让 latest_successful_broadcast 返回当前 (status, status_changed_at)
    p = cache.get("PRJ-001")
    store.latest_successful_broadcast = MagicMock(return_value=(
        p.status.value, p.status_changed_at.isoformat()
    ))
    svc = BroadcastSvc(bot_service, mapping_repo, store, cache, ADMIN_ID,
                       retry_delays=(0, 0, 0))
    result = await svc.broadcast_all(skip_if_no_change=True, dryrun=False)
    assert result["sent"] == 0
    assert result["skipped"] == 1
    bot_service.send_message.assert_not_awaited()


async def test_does_not_skip_when_status_changed():
    bot_service, mapping_repo, store, cache = _deps()
    # 上次 status 是 ORDERED（不同），所以不应 skip
    store.latest_successful_broadcast = MagicMock(return_value=(
        StatusCode.ORDERED.value, datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc).isoformat()
    ))
    svc = BroadcastSvc(bot_service, mapping_repo, store, cache, ADMIN_ID,
                       retry_delays=(0, 0, 0))
    result = await svc.broadcast_all(skip_if_no_change=True, dryrun=False)
    assert result["sent"] == 1


# ---------- retry / backoff ----------

async def test_retry_on_send_failure_then_success():
    # 前两次失败，第三次成功
    side_effects = [RuntimeError("telegram api down"),
                    RuntimeError("telegram api down"),
                    None]
    bot_service, mapping_repo, store, cache = _deps(send_message_side_effect=side_effects)
    svc = BroadcastSvc(bot_service, mapping_repo, store, cache, ADMIN_ID,
                       retry_delays=(0, 0, 0))  # 测试用 0 延迟
    result = await svc.broadcast_all(skip_if_no_change=False, dryrun=False)
    assert result["sent"] == 1
    assert bot_service.send_message.await_count == 3


async def test_final_failure_records_error_and_counts_failed():
    bot_service, mapping_repo, store, cache = _deps(
        send_message_side_effect=RuntimeError("boom")
    )
    svc = BroadcastSvc(bot_service, mapping_repo, store, cache, ADMIN_ID,
                       retry_delays=(0, 0, 0))
    result = await svc.broadcast_all(skip_if_no_change=False, dryrun=False)
    assert result["sent"] == 0
    assert result["failed"] == 1
    # retry_delays 长度 3 → 4 次尝试（首 + 3 重试）；也允许 3 次（len+1）视实现
    assert bot_service.send_message.await_count >= 1
    # last_error 被写入 save_mapping_snapshot
    mapping = mapping_repo.load_all.return_value[0]
    assert mapping.last_error is not None
    assert "❌" in mapping.last_error or "无法发送" in mapping.last_error


# ---------- threshold ----------

async def test_exceeded_threshold_marks_warning_in_message():
    bot_service, mapping_repo, store, cache = _deps()
    long_ago = datetime.now(timezone.utc) - timedelta(days=30)
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.CLIENT_REVIEW,
        status_changed_at=long_ago,
        status_history=[(StatusCode.CLIENT_REVIEW, long_ago)],
        sheets=[],
    )
    cache.replace([p])
    svc = BroadcastSvc(
        bot_service, mapping_repo, store, cache, ADMIN_ID,
        per_status_thresholds={"CLIENT_REVIEW": 7},
        retry_delays=(0, 0, 0),
    )
    await svc.broadcast_all(skip_if_no_change=False, dryrun=False)
    sent_text = bot_service.send_message.await_args.args[1]
    assert "⚠" in sent_text


# ---------- dryrun ----------

async def test_dryrun_does_not_send_or_log():
    bot_service, mapping_repo, store, cache = _deps()
    svc = BroadcastSvc(bot_service, mapping_repo, store, cache, ADMIN_ID,
                       retry_delays=(0, 0, 0))
    result = await svc.broadcast_all(dryrun=True)
    assert result["dryrun"] is True
    assert "preview" in result
    bot_service.send_message.assert_not_awaited()
    store.log_broadcast.assert_not_called()


# ---------- disabled mapping skipped ----------

async def test_disabled_mapping_skipped():
    bot_service, mapping_repo, store, cache = _deps()
    mapping_repo.load_all = MagicMock(return_value=[_mapping(enabled=False)])
    svc = BroadcastSvc(bot_service, mapping_repo, store, cache, ADMIN_ID,
                       retry_delays=(0, 0, 0))
    result = await svc.broadcast_all(skip_if_no_change=False, dryrun=False)
    assert result["sent"] == 0
    assert result["skipped"] == 0  # 也不算 skipped（不算 enabled）
    bot_service.send_message.assert_not_awaited()


# ---------- missing project in cache ----------

async def test_project_not_in_cache_is_skipped():
    bot_service, mapping_repo, store, cache = _deps()
    cache.replace([])  # cache 空
    svc = BroadcastSvc(bot_service, mapping_repo, store, cache, ADMIN_ID,
                       retry_delays=(0, 0, 0))
    result = await svc.broadcast_all(skip_if_no_change=False, dryrun=False)
    assert result["sent"] == 0
    bot_service.send_message.assert_not_awaited()
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_bot_broadcast.py -v
```

Expected: FAIL。

- [ ] **Step 3: 实现 `src/bot/broadcast.py`**

```python
"""BroadcastSvc：全员播报服务。

对每条 enabled 映射：
1. cache.get(project_id) 拿 Project
2. 计算 dwell_seconds、判定是否超阈值
3. skip_if_no_change 且与上次成功播报完全相同 → skip
4. 渲染 Markdown → BotService.send_message
5. 失败 1s/2s/4s 指数退避；最终失败 → mapping.last_error = "❌ 无法发送"
6. 成功 → store.log_broadcast + store.record_status + store.save_mapping_snapshot

dryrun=True 时只渲染首条 enabled 映射的 preview，不发、不写 log。

管理员告警：失败 > 0 时调 notify_admin（懒加载，避免循环 import）。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from src.bot.service import BotService
from src.bot.templates import render_broadcast, render_dryrun_preview
from src.models.project import Mapping
from src.sheets.mapping_repo import MappingRepo
from src.store.db import Store
from src.web.cache import ProjectCache


class BroadcastSvc:
    def __init__(
        self,
        bot_service: BotService,
        mapping_repo: MappingRepo,
        store: Store,
        cache: ProjectCache,
        admin_chat_id: int,
        *,
        per_status_thresholds: Optional[dict[str, int]] = None,
        retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0),
    ) -> None:
        self.bot_service = bot_service
        self.mapping_repo = mapping_repo
        self.store = store
        self.cache = cache
        self.admin_chat_id = admin_chat_id
        # 默认 14 天阈值
        self.per_status_thresholds: dict[str, int] = {
            "MAKING": 14, "CLIENT_REVIEW": 7, "UNPAID": 30,
            **(per_status_thresholds or {}),
        }
        self.retry_delays = retry_delays

    def _exceeded_threshold(self, project) -> bool:
        if project.status is None or project.status_changed_at is None:
            return False
        dwell_days = (datetime.now(timezone.utc) - project.status_changed_at).days
        threshold = self.per_status_thresholds.get(project.status.value, 14)
        return dwell_days > threshold

    async def _send_with_retry(self, chat_id: str | int, text: str) -> bool:
        """返回 True = 成功，False = 全部重试失败。"""
        last_error: Optional[BaseException] = None
        # 首发 + len(retry_delays) 次重试
        for attempt in range(len(self.retry_delays) + 1):
            try:
                await self.bot_service.send_message(chat_id, text)
                return True
            except Exception as e:  # noqa: BLE001
                last_error = e
                if attempt < len(self.retry_delays):
                    await asyncio.sleep(self.retry_delays[attempt])
        # 记录最终异常供 caller 写 last_error
        self._last_send_error = last_error
        return False

    async def broadcast_all(
        self,
        skip_if_no_change: bool = True,
        dryrun: bool = False,
    ) -> dict:
        """全员播报。

        Returns:
            {sent, skipped, failed, dryrun, preview?}
        """
        self._last_send_error = None

        # mapping_repo.load_all 同步 gspread → to_thread
        try:
            mappings: list[Mapping] = await asyncio.to_thread(self.mapping_repo.load_all)
        except Exception:  # noqa: BLE001
            mappings = []  # 整段失败视为无可播报

        sent = 0
        skipped = 0
        failed = 0
        first_preview: Optional[str] = None

        for m in mappings:
            if not m.enabled:
                continue
            project = self.cache.get(m.project_id)
            if project is None:
                # cache 里没该项目（refresher 未拉到）→ skip
                continue

            now = datetime.now(timezone.utc)
            exceeded = self._exceeded_threshold(project)

            # skip_if_no_change 判定
            if skip_if_no_change and project.status is not None and project.status_changed_at:
                last = self.store.latest_successful_broadcast(m.project_id, m.chat_id)
                if last is not None:
                    last_code, last_text = last
                    curr_signature = (
                        project.status.value,
                        project.status_changed_at.isoformat(),
                    )
                    last_signature = (last_code, last_text)
                    # last_text 是 message_text 整段；这里按 spec 改为比对 (status_code, status_changed_at)
                    # latest_successful_broadcast 返回 (status_code, message_text)
                    # message_text 在 skip 判定里不直接用；改用 status_changed_at
                    # 因此上层要重新组织返回值；这里用一个简化的等价判定：
                    # 我们假定 latest_successful_broadcast() 返回元组的 [1] 是 status_changed_at 字符串
                    # （由 T5 的 store 实现保证；本期修改 store 使其返回 status_changed_at）
                    # 见 src/store/db.py latest_successful_broadcast_with_changed_at
                    if curr_signature[1] == last_signature[1]:
                        skipped += 1
                        continue

            text = render_broadcast(project, m, now, exceeded)

            if dryrun:
                first_preview = render_dryrun_preview(project, m, now)
                continue  # 不发不写 log

            ok = await self._send_with_retry(m.chat_id, text)
            sent_at = datetime.now(timezone.utc)
            if ok:
                sent += 1
                self.store.log_broadcast(
                    project_id=m.project_id,
                    chat_id=m.chat_id,
                    status_code=project.status.value if project.status else "UNKNOWN",
                    message_text=text,
                    sent_at=sent_at,
                    success=True,
                    error=None,
                )
                if project.status and project.status_changed_at:
                    self.store.record_status(
                        m.project_id, project.status.value, project.status_changed_at
                    )
            else:
                failed += 1
                m.last_error = f"❌ 无法发送: {self._last_send_error}"
                await asyncio.to_thread(self.store.save_mapping_snapshot, m)

        # 失败汇总 → 管理员告警
        if failed > 0 and not dryrun:
            from src.bot.notifications import notify_admin

            await notify_admin(
                self.bot_service, self.admin_chat_id,
                f"⚠ 播报部分失败: sent={sent} skipped={skipped} failed={failed}",
            )

        result = {
            "sent": sent, "skipped": skipped, "failed": failed,
            "dryrun": dryrun,
        }
        if first_preview is not None:
            result["preview"] = first_preview
        return result
```

- [ ] **Step 4: 扩展 `Store.latest_successful_broadcast` 返回 status_changed_at**

修改 `src/store/db.py`，把方法签名扩展为返回三元组：

Edit `src/store/db.py`：

```python
    def latest_successful_broadcast(
        self, project_id: str, chat_id: str
    ) -> Optional[tuple[str, str]]:
        """返回 (status_code, message_text)。Phase 3 broadcast.py 用于 skip_if_no_change 判定。"""
```

替换为：

```python
    def latest_successful_broadcast(
        self, project_id: str, chat_id: str
    ) -> Optional[tuple[str, str]]:
        """返回 (status_code, message_text)。

        Phase 3 broadcast.py 的 skip_if_no_change 判定依赖 message_text 中的
        status_changed_at 锚点；为了精确判定，本方法实际把 message_text 中的
        第一行（"📊 *PRJ-001 ..."）之外的状态码 + 文本嵌入约定：把
        status_changed_at 写到 broadcast_log.message_text 的最后一行 sentinel。
        为简化，这里直接扩展方法返回 (status_code, status_changed_at_iso)。

        为保持旧测试兼容，我们改为返回三元组 (status_code, status_changed_at, message_text)：
        """
        with self._conn() as conn:
            row = conn.execute(
                """SELECT bl.status_code, bl.message_text, sh.detected_at
                   FROM broadcast_log bl
                   LEFT JOIN status_history sh
                     ON sh.project_id = bl.project_id
                    AND sh.status_code = bl.status_code
                   WHERE bl.project_id = ? AND bl.chat_id = ? AND bl.success = 1
                   ORDER BY bl.sent_at DESC LIMIT 1""",
                (project_id, chat_id),
            ).fetchone()
        if row is None:
            return None
        # 返回三元组 (status_code, detected_at_iso, message_text)；
        # 测试与 broadcast.py 消费方按位置 0/1 读
        return (row["status_code"], row["detected_at"] or "", row["message_text"])
```

> 说明：T5 的 broadcast.py 只用 `last_signature[1]`，对应 detected_at；保持兼容性
> 我们让 broadcast.py 解构为三段；同时把 src/store/db.py 第 166-180 行
> 原本 docstring "返回 (status_code, message_text)" 同步更新。

再修 broadcast.py 解构处：

```python
            # skip_if_no_change 判定
            if skip_if_no_change and project.status is not None and project.status_changed_at:
                last = self.store.latest_successful_broadcast(m.project_id, m.chat_id)
                if last is not None:
                    last_code, last_changed_at, _last_text = last
                    curr_changed_at = project.status_changed_at.isoformat()
                    if last_changed_at == curr_changed_at and last_code == project.status.value:
                        skipped += 1
                        continue
```

> 修改位置：在 `src/bot/broadcast.py` 的 `broadcast_all` 内，替换原 `last_signature` 段。

- [ ] **Step 5: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_bot_broadcast.py -v
```

Expected: 9 passed。

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
git add src/bot/broadcast.py src/store/db.py tests/test_bot_broadcast.py
git commit -m "feat(phase3): BroadcastSvc with skip_if_no_change and exponential backoff"
```

---

## Task 6: AsyncIOScheduler + scheduler.yaml 加载

**Files:**
- Create: `config/scheduler.yaml.example`
- Create: `src/scheduler/__init__.py`
- Create: `src/scheduler/config.py`
- Create: `src/scheduler/jobs.py`
- Create: `tests/test_scheduler_config.py`

**Interfaces:**
- Consumes: yaml、APScheduler
- Produces:
  ```python
  # src/scheduler/config.py
  @dataclass
  class BroadcastConfig:
      times: list[str]            # ["09:00", "18:00"]
      weekdays_only: bool
      skip_if_no_change: bool
      per_status_thresholds: dict[str, int]

  def load_scheduler_config(path: Path) -> BroadcastConfig: ...

  # src/scheduler/jobs.py
  def build_scheduler(broadcast_cfg: BroadcastConfig) -> AsyncIOScheduler: ...

  async def broadcast_job(broadcast_svc: BroadcastSvc, broadcast_cfg: BroadcastConfig) -> None:
      """工作日过滤 + 调 broadcast_all"""
  ```

- [ ] **Step 1: 写失败测试 `tests/test_scheduler_config.py`**

```python
"""scheduler 配置加载测试。"""
from pathlib import Path

import pytest

from src.scheduler.config import BroadcastConfig, load_scheduler_config


def test_load_scheduler_config_full(tmp_path: Path):
    p = tmp_path / "scheduler.yaml"
    p.write_text(
        "broadcast:\n"
        "  times: ['09:00', '18:00']\n"
        "  weekdays_only: true\n"
        "  skip_if_no_change: true\n"
        "  per_status_thresholds:\n"
        "    MAKING: 14\n"
        "    CLIENT_REVIEW: 7\n",
        encoding="utf-8",
    )
    cfg = load_scheduler_config(p)
    assert isinstance(cfg, BroadcastConfig)
    assert cfg.times == ["09:00", "18:00"]
    assert cfg.weekdays_only is True
    assert cfg.skip_if_no_change is True
    assert cfg.per_status_thresholds == {"MAKING": 14, "CLIENT_REVIEW": 7}


def test_load_scheduler_config_defaults(tmp_path: Path):
    p = tmp_path / "scheduler.yaml"
    p.write_text("broadcast:\n  times: ['10:00']\n", encoding="utf-8")
    cfg = load_scheduler_config(p)
    assert cfg.times == ["10:00"]
    assert cfg.weekdays_only is True  # 默认
    assert cfg.skip_if_no_change is True
    assert cfg.per_status_thresholds == {}


def test_load_scheduler_config_missing_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_scheduler_config(tmp_path / "nope.yaml")


def test_times_must_be_hhmm_format(tmp_path: Path):
    p = tmp_path / "scheduler.yaml"
    p.write_text("broadcast:\n  times: ['bad-time']\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_scheduler_config(p)
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_scheduler_config.py -v
```

Expected: FAIL。

- [ ] **Step 3: 创建 `config/scheduler.yaml.example`**

```yaml
# checkGPRobot 调度策略模板（实际配置复制为 scheduler.yaml）
broadcast:
  times:
    - "09:00"
    - "18:00"
  weekdays_only: true   # 周六周日不播
  skip_if_no_change: true  # 状态无变化时跳过（避免刷屏）
  per_status_thresholds:
    MAKING: 14          # 超过 14 天 → ⚠
    CLIENT_REVIEW: 7
    UNPAID: 30
```

- [ ] **Step 4: 创建 `src/scheduler/__init__.py`**

```python
"""src.scheduler 子包：APScheduler 包装。

- config.py  BroadcastConfig 数据类 + yaml 加载
- jobs.py    build_scheduler + broadcast_job
"""
```

- [ ] **Step 5: 实现 `src/scheduler/config.py`**

```python
"""scheduler.yaml 加载与校验。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass
class BroadcastConfig:
    times: list[str] = field(default_factory=lambda: ["09:00", "18:00"])
    weekdays_only: bool = True
    skip_if_no_change: bool = True
    per_status_thresholds: dict[str, int] = field(default_factory=dict)


def load_scheduler_config(path: Path) -> BroadcastConfig:
    """读 config/scheduler.yaml，返回 BroadcastConfig。

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: times 格式错误 / 缺 broadcast 段
    """
    if not path.exists():
        raise FileNotFoundError(f"Scheduler config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    bc = raw.get("broadcast")
    if not isinstance(bc, dict):
        raise ValueError("scheduler.yaml missing 'broadcast:' section")

    times = bc.get("times") or ["09:00", "18:00"]
    if not isinstance(times, list) or not times:
        raise ValueError("broadcast.times must be a non-empty list")
    for t in times:
        if not isinstance(t, str) or not _HHMM_RE.match(t):
            raise ValueError(f"invalid time format: {t!r} (expected HH:MM)")

    return BroadcastConfig(
        times=list(times),
        weekdays_only=bool(bc.get("weekdays_only", True)),
        skip_if_no_change=bool(bc.get("skip_if_no_change", True)),
        per_status_thresholds=dict(bc.get("per_status_thresholds") or {}),
    )
```

- [ ] **Step 6: 实现 `src/scheduler/jobs.py`**

```python
"""APScheduler AsyncIOScheduler 构建 + 广播 job。

build_scheduler: 注册 N 个 cron 触发器（每个 times 一条），全部指向 broadcast_job。
broadcast_job: 工作日过滤（weekdays_only）→ 调 BroadcastSvc.broadcast_all。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.bot.broadcast import BroadcastSvc
from src.scheduler.config import BroadcastConfig


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def build_scheduler(
    broadcast_svc: BroadcastSvc,
    broadcast_cfg: BroadcastConfig,
) -> AsyncIOScheduler:
    """构造并配置 AsyncIOScheduler，注册 broadcast job。"""
    scheduler = AsyncIOScheduler()

    for t in broadcast_cfg.times:
        hour, minute = _parse_hhmm(t)
        trigger = CronTrigger(hour=hour, minute=minute, timezone="UTC")
        scheduler.add_job(
            _broadcast_job_wrapper,
            trigger=trigger,
            args=(broadcast_svc, broadcast_cfg),
            id=f"broadcast-{t}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    return scheduler


async def _broadcast_job_wrapper(
    broadcast_svc: BroadcastSvc, broadcast_cfg: BroadcastConfig
) -> None:
    """被 APScheduler 调用的同步入口；内部再分流。"""
    if broadcast_cfg.weekdays_only:
        # weekday(): Monday=0 ... Sunday=6
        if datetime.now(timezone.utc).weekday() >= 5:
            return
    await broadcast_svc.broadcast_all(
        skip_if_no_change=broadcast_cfg.skip_if_no_change,
        dryrun=False,
    )
```

- [ ] **Step 7: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_scheduler_config.py -v
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
git add config/scheduler.yaml.example src/scheduler/ tests/test_scheduler_config.py
git commit -m "feat(phase3): AsyncIOScheduler + scheduler.yaml loader with weekdays_only filter"
```

---

## Task 7: notify_admin — 管理员告警通道

**Files:**
- Create: `src/bot/notifications.py`
- Create: `tests/test_bot_notifications.py`

**Interfaces:**
- Consumes: `BotService`、`admin_chat_id`、`message`
- Produces:
  ```python
  # src/bot/notifications.py
  async def notify_admin(
      bot_service: BotService,
      admin_chat_id: int | str,
      message: str,
      *,
      retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0),
  ) -> bool:
      """返回 True = 至少一次成功发送；False = 全部失败。"""
  ```

- [ ] **Step 1: 写失败测试 `tests/test_bot_notifications.py`**

```python
"""notify_admin 测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.notifications import notify_admin


pytestmark = pytest.mark.asyncio


async def test_notify_admin_success_first_try():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    ok = await notify_admin(bot, 42, "hello", retry_delays=(0, 0, 0))
    assert ok is True
    bot.send_message.assert_awaited_once()
    args = bot.send_message.await_args
    assert args.args[0] == 42
    assert args.args[1] == "hello"


async def test_notify_admin_retries_then_success():
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=[RuntimeError("net"), None])
    ok = await notify_admin(bot, 42, "hi", retry_delays=(0, 0, 0))
    assert ok is True
    assert bot.send_message.await_count == 2


async def test_notify_admin_returns_false_on_total_failure():
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("down"))
    ok = await notify_admin(bot, 42, "hi", retry_delays=(0, 0, 0))
    assert ok is False
    assert bot.send_message.await_count == 4  # 1 + 3 retry
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_bot_notifications.py -v
```

Expected: FAIL。

- [ ] **Step 3: 实现 `src/bot/notifications.py`**

```python
"""管理员告警通道。

notify_admin(bot_service, admin_chat_id, message):
    1s/2s/4s 指数退避；至少一次成功 → True；全失败 → False（不抛）。

供 BroadcastSvc 在 partial failure 时调用。
"""
from __future__ import annotations

import asyncio
from typing import Union

from src.bot.service import BotService


async def notify_admin(
    bot_service: BotService,
    admin_chat_id: Union[int, str],
    message: str,
    *,
    retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0),
) -> bool:
    """发送管理员告警；返回 True 表示至少一次成功。"""
    last_error: Exception | None = None
    for attempt in range(len(retry_delays) + 1):
        try:
            await bot_service.send_message(admin_chat_id, message)
            return True
        except Exception as e:  # noqa: BLE001
            last_error = e
            if attempt < len(retry_delays):
                await asyncio.sleep(retry_delays[attempt])
    # 全失败：返回 False；不抛（让 BroadcastSvc 继续跑）
    return False
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_bot_notifications.py -v
```

Expected: 3 passed。

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
git add src/bot/notifications.py tests/test_bot_notifications.py
git commit -m "feat(phase3): notify_admin with exponential backoff retry"
```

---

## Task 8: FastAPI lifespan 启停 BotService + Scheduler

**Files:**
- Modify: `src/web/app.py`
- Create: `tests/test_lifespan_integration.py`

**Interfaces:**
- Consumes: `BotService`、`AsyncIOScheduler`、`admin_chat_id`、`bot token`
- Produces:
  ```python
  # src/web/app.py — 新增 lifespan 集成
  # create_app 接受可选 bot_service + scheduler；保存到 app.state
  # 启动：bot_service.start(token) → register_handlers → scheduler.start
  # 关闭：scheduler.shutdown(wait=False) → bot_service.stop
  ```

- [ ] **Step 1: 写失败测试 `tests/test_lifespan_integration.py`**

```python
"""lifespan 上下文测试：用 fake bot/scheduler 验证 start/stop 调用。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


def _make_app_with_fakes():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    cfg.telegram_bot_token = "test-token"

    bot_service = MagicMock()
    bot_service.start = AsyncMock()
    bot_service.stop = AsyncMock()
    bot_service._app = MagicMock()  # 假装 PTB Application 已构造
    # register_handlers 要往 bot_service._app 上挂 handler，我们让它无操作即可
    bot_service._app.add_handler = MagicMock()
    bot_service._app.bot_data = {}

    scheduler = MagicMock()
    scheduler.start = MagicMock()
    scheduler.shutdown = MagicMock()
    scheduler.get_jobs = MagicMock(return_value=[])

    store = MagicMock()
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()

    app = create_app(
        cfg, store, sheet_repo, mapping_repo,
        bot_service=bot_service, scheduler=scheduler,
        admin_chat_id=42,
    )
    return app, bot_service, scheduler


def test_create_app_accepts_bot_and_scheduler():
    app, bot, sch = _make_app_with_fakes()
    assert app.state.bot_service is bot
    assert app.state.scheduler is sch
    assert app.state.admin_chat_id == 42


def test_lifespan_starts_bot_and_scheduler():
    app, bot, sch = _make_app_with_fakes()
    with TestClient(app) as client:
        # lifespan startup 应已触发
        bot.start.assert_awaited_once()
        bot._app.add_handler.assert_called()  # register_handlers
        sch.start.assert_called_once()
        r = client.get("/health")
        assert r.status_code == 200


def test_lifespan_shuts_down_in_reverse_order():
    app, bot, sch = _make_app_with_fakes()
    with TestClient(app):
        pass  # 退出 with 触发 shutdown
    sch.shutdown.assert_called_once_with(wait=False)
    bot.stop.assert_awaited_once()


def test_lifespan_handles_missing_scheduler_gracefully():
    """scheduler=None 时应只启停 bot，不报错。"""
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    cfg.telegram_bot_token = "tok"
    bot = MagicMock()
    bot.start = AsyncMock()
    bot.stop = AsyncMock()
    bot._app = MagicMock()
    bot._app.add_handler = MagicMock()
    bot._app.bot_data = {}

    app = create_app(
        cfg, MagicMock(), MagicMock(), MagicMock(),
        bot_service=bot, scheduler=None, admin_chat_id=1,
    )
    with TestClient(app):
        bot.start.assert_awaited_once()
    bot.stop.assert_awaited_once()
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_lifespan_integration.py -v
```

Expected: FAIL。

- [ ] **Step 3: 修改 `src/web/app.py` —— 注入 lifespan + 新参数**

替换 `src/web/app.py` 全文：

```python
"""FastAPI 应用工厂。

create_app() 接收 Phase 1+2 的 deps + Phase 3 的 bot_service / scheduler，
构造 FastAPI 实例，注册 Jinja2 环境（autoescape=True）、自定义过滤器、
`/health` 路由，并在 app.state 挂上所有依赖供后续路由访问。

Phase 3：增加 lifespan context manager，启动 BotService + Scheduler，
关闭时反向释放。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles
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
    scheduler: Optional[object] = None,
    admin_chat_id: Optional[int] = None,
) -> FastAPI:
    """构造并返回 FastAPI 应用实例。

    Args:
        bot_service: Phase 3 注入 BotService 实例；为 None 时 lifespan 跳过 bot 启动。
        scheduler: Phase 3 注入 AsyncIOScheduler 实例；为 None 时跳过。
        admin_chat_id: 管理员 Telegram user id（int）；为 None 时 bot 命令 admin gate 全放行。
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # === 启动 ===
        if bot_service is not None:
            await bot_service.start(cfg.telegram_bot_token)
            # 注册命令处理器
            from src.bot.commands import register_handlers

            cache = app.state.cache
            broadcast_svc = app.state.broadcast_svc
            store_ref = app.state.store
            register_handlers(
                bot_service._app,
                admin_chat_id=admin_chat_id or 0,
                cache=cache,
                broadcast_svc=broadcast_svc,
                bot_service=bot_service,
                store=store_ref,
            )
            bot_service._app.bot_data["mapping_repo"] = mapping_repo

        if scheduler is not None:
            scheduler.start()

        try:
            yield
        finally:
            # === 关闭 ===
            if scheduler is not None:
                try:
                    scheduler.shutdown(wait=False)
                except Exception:  # noqa: BLE001
                    pass
            if bot_service is not None:
                try:
                    await bot_service.stop()
                except Exception:  # noqa: BLE001
                    pass

    app = FastAPI(title="checkGPRobot UI", docs_url=None, redoc_url=None, lifespan=lifespan)

    # 挂依赖到 app.state 供路由访问
    app.state.cfg = cfg
    app.state.store = store
    app.state.sheet_repo = sheet_repo
    app.state.mapping_repo = mapping_repo
    app.state.bot_service = bot_service
    app.state.scheduler = scheduler
    app.state.admin_chat_id = admin_chat_id
    app.state.cache = None  # T3 注入 ProjectCache
    app.state.broadcast_svc = None  # Phase 3 注入 BroadcastSvc

    # Jinja2 环境（autoescape 默认 on：.html/.xml/.htm；这里强制 on 更稳）
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    templates.env.autoescape = True
    templates.env.filters["status_badge"] = status_badge
    templates.env.filters["humanize_duration"] = humanize_duration
    app.state.templates = templates

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # 路由（T3 注册 overview，T5 注册 project detail，T10a 注册 mappings）
    from src.web.routes import pages as pages_routes
    app.include_router(pages_routes.router)
    from src.web.routes import api as api_routes
    app.include_router(api_routes.router)

    # 静态资源（CSS / JS）—— T7a 完成
    app.mount("/static", StaticFiles(directory="src/web/static"), name="static")

    return app
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_lifespan_integration.py -v
```

Expected: 4 passed。

- [ ] **Step 5: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS（部分 Phase 2 测试用 `create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)` 仍兼容，因为新参数都有默认值）。

- [ ] **Step 6: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add src/web/app.py tests/test_lifespan_integration.py
git commit -m "feat(phase3): FastAPI lifespan starts BotService + Scheduler and shuts down"
```

---

## Task 9: /api/mappings/{project_id}/test-send 真正调用 bot

**Files:**
- Modify: `src/web/routes/api.py`
- Create: `tests/test_api_test_send.py`

**Interfaces:**
- Consumes: `bot_service`（app.state）
- Produces:
  ```python
  # src/web/routes/api.py — POST /api/mappings/{project_id}/test-send
  # body: {chat_id?: str}  (可选；默认取 mapping.chat_id)
  # 200: {ok: true, chat_id, message_preview}
  # 404: project / mapping 不存在
  # 503: bot_service is None
  # 502: Telegram API 失败
  ```

- [ ] **Step 1: 写失败测试 `tests/test_api_test_send.py`**

```python
"""/api/mappings/{id}/test-send 测试（Phase 3 真正激活）。"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.models.project import Field, Mapping, Project, SheetView
from src.models.status import StatusCode
from src.web.app import create_app
from src.web.cache import ProjectCache


def _app_with_bot(bot_service=None):
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    app = create_app(cfg, MagicMock(), MagicMock(), MagicMock(),
                     bot_service=bot_service)
    cache = ProjectCache()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        status_history=[(StatusCode.MAKING, datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc))],
        sheets=[SheetView(
            spreadsheet_id="ss1", sheet_name="项目主表",
            fields=[Field(name="项目编号", value="PRJ-001",
                          column_index=1, row_index=2, recognized_as="project_id")],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    app.state.cache = cache
    mapping_repo = MagicMock()
    mapping_repo.load_all = MagicMock(return_value=[Mapping(
        project_id="PRJ-001", chat_id="123456",
        note="", enabled=True,
        last_broadcast_at=None, last_broadcast_status=None, last_error=None,
    )])
    app.state.mapping_repo = mapping_repo
    return TestClient(app), app


def test_test_send_503_when_no_bot():
    client, _ = _app_with_bot(bot_service=None)
    r = client.post("/api/mappings/PRJ-001/test-send", json={})
    assert r.status_code == 503
    assert "bot" in r.json()["detail"].lower() or "未配置" in r.json()["detail"]


def test_test_send_404_when_no_mapping():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    client, app = _app_with_bot(bot_service=bot)
    app.state.mapping_repo.load_all = MagicMock(return_value=[])
    r = client.post("/api/mappings/PRJ-001/test-send", json={})
    assert r.status_code == 404


def test_test_send_200_calls_bot():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    client, app = _app_with_bot(bot_service=bot)
    r = client.post("/api/mappings/PRJ-001/test-send", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["chat_id"] == "123456"
    assert "PRJ-001" in body["message_preview"]
    bot.send_message.assert_awaited_once()


def test_test_send_502_when_bot_fails():
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))
    client, _ = _app_with_bot(bot_service=bot)
    r = client.post("/api/mappings/PRJ-001/test-send", json={})
    assert r.status_code == 502
    assert "telegram" in r.json()["detail"].lower() or "无法发送" in r.json()["detail"]


def test_test_send_override_chat_id():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    client, _ = _app_with_bot(bot_service=bot)
    r = client.post("/api/mappings/PRJ-001/test-send", json={"chat_id": "999"})
    assert r.status_code == 200
    # bot.send_message 的第一参数
    assert bot.send_message.await_args.args[0] == "999"
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_api_test_send.py -v
```

Expected: FAIL（路由不存在或返回 503）。

- [ ] **Step 3: 修改 `src/web/routes/api.py` —— 添加 test-send 路由**

打开 `src/web/routes/api.py`，在文件末尾追加（导入段不变）：

```python
from src.bot.templates import render_broadcast
from datetime import datetime, timezone


@router.post("/mappings/{project_id}/test-send")
async def post_test_send(request: Request, project_id: str):
    """立即渲染文案并发送给该项目的映射 chat（用于 UI "测试发送"按钮）。"""
    app = request.app
    bot_service = app.state.bot_service
    if bot_service is None:
        raise HTTPException(status_code=503, detail="Telegram bot not configured")

    # 解析 mapping
    import asyncio as _asyncio
    mapping_repo = app.state.mapping_repo
    mappings = await _asyncio.to_thread(mapping_repo.load_all)
    mapping = next((m for m in mappings if m.project_id == project_id), None)
    if mapping is None:
        raise HTTPException(status_code=404, detail=f"mapping for {project_id} not found")

    # 读 project
    cache = app.state.cache
    project = cache.get(project_id) if cache else None
    if project is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not in cache")

    # 读 chat_id override
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    chat_id = body.get("chat_id") or mapping.chat_id
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id not specified")

    now = datetime.now(timezone.utc)
    text = render_broadcast(project, mapping, now, exceeded_threshold=False)

    try:
        await bot_service.send_message(chat_id, text)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"telegram send failed: {e}")

    return {
        "ok": True,
        "chat_id": chat_id,
        "message_preview": text,
    }
```

> 复用 Phase 2 已在 `src/web/routes/api.py` 顶部 import 过的 `Request`、`HTTPException`、`router`、`Optional`。
> 若原文件没 import 这些，把缺失的 import 加到顶部。

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_api_test_send.py -v
```

Expected: 5 passed。

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
git add src/web/routes/api.py tests/test_api_test_send.py
git commit -m "feat(phase3): activate /api/mappings/{id}/test-send with real bot_service"
```

---

## Task 10: E2E 测试 — 完整播报流水线

**Files:**
- Create: `tests/test_e2e_broadcast_flow.py`

**Interfaces:**
- Consumes: 全套 fake（BotService、MappingRepo、Store、ProjectCache、Scheduler）
- Produces: 一个测试函数集合，覆盖：
  - 调度触发 → BroadcastSvc → mapping 查表 → 模板渲染 → send_message → store.log_broadcast → store.record_status（happy path）
  - skip_if_no_change：上次成功记录匹配 → 不发送
  - retry on failure：前两次失败第三次成功 → sent + log_broadcast success=True
  - final failure：全部重试失败 → failed=1, mapping.last_error 写入, notify_admin 调用
  - disabled mapping 跳过
  - cache miss 跳过
  - dryrun：不发不写 log

- [ ] **Step 1: 写失败测试 `tests/test_e2e_broadcast_flow.py`**

```python
"""Phase 3 端到端播报流测试。

模拟 APScheduler 触发 → BroadcastSvc.broadcast_all → 全套依赖的协同。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.broadcast import BroadcastSvc
from src.bot.service import BotService
from src.models.project import Mapping, Project
from src.models.status import StatusCode
from src.scheduler.config import BroadcastConfig
from src.scheduler.jobs import build_scheduler, _broadcast_job_wrapper
from src.web.cache import ProjectCache


pytestmark = pytest.mark.asyncio


def _project(pid="PRJ-001", status=StatusCode.MAKING,
             changed_at: datetime | None = None,
             history=None):
    return Project(
        project_id=pid, project_name=f"项目{pid}",
        status=status,
        status_changed_at=changed_at or datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        status_history=history or [(status, changed_at or datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc))],
        sheets=[],
    )


def _mapping(pid="PRJ-001", chat_id="100", enabled=True):
    return Mapping(
        project_id=pid, chat_id=chat_id, note="", enabled=enabled,
        last_broadcast_at=None, last_broadcast_status=None, last_error=None,
    )


def _fixtures(*, latest=None, side_effects=None, enabled=True, extra_mappings=None):
    bot = MagicMock(spec=BotService)
    bot.send_message = AsyncMock(side_effect=side_effects)

    mr = MagicMock()
    all_mappings = [_mapping(enabled=enabled)]
    if extra_mappings:
        all_mappings.extend(extra_mappings)
    mr.load_all = MagicMock(return_value=all_mappings)

    store = MagicMock()
    store.latest_successful_broadcast = MagicMock(return_value=latest)
    store.log_broadcast = MagicMock()
    store.record_status = MagicMock()
    store.save_mapping_snapshot = MagicMock()

    cache = ProjectCache()
    cache.replace([_project()])

    return bot, mr, store, cache


# ---------- happy path: scheduler fires → broadcast_all → sent ----------

async def test_e2e_scheduler_wrapper_triggers_broadcast():
    bot, mr, store, cache = _fixtures()
    svc = BroadcastSvc(bot, mr, store, cache, admin_chat_id=42,
                       retry_delays=(0, 0, 0))
    cfg = BroadcastConfig(times=["09:00", "18:00"], weekdays_only=True,
                          skip_if_no_change=True)
    scheduler = build_scheduler(svc, cfg)
    # 直接调 wrapper，绕过 cron
    await _broadcast_job_wrapper(svc, cfg)

    bot.send_message.assert_awaited_once()
    store.log_broadcast.assert_called_once()
    # log 第二个位置是 chat_id
    kwargs = store.log_broadcast.call_args.kwargs
    assert kwargs["project_id"] == "PRJ-001"
    assert kwargs["chat_id"] == "100"
    assert kwargs["success"] is True
    store.record_status.assert_called_once()


# ---------- skip ----------

async def test_e2e_skip_when_no_change():
    changed = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    bot, mr, store, cache = _fixtures(latest=(StatusCode.MAKING.value, changed.isoformat(), ""))
    svc = BroadcastSvc(bot, mr, store, cache, admin_chat_id=42,
                       retry_delays=(0, 0, 0))
    cfg = BroadcastConfig(skip_if_no_change=True)
    await _broadcast_job_wrapper(svc, cfg)

    bot.send_message.assert_not_awaited()
    store.log_broadcast.assert_not_called()


# ---------- retry then success ----------

async def test_e2e_retry_then_success():
    side_effects = [RuntimeError("net"), RuntimeError("net"), None]
    bot, mr, store, cache = _fixtures(side_effects=side_effects)
    svc = BroadcastSvc(bot, mr, store, cache, admin_chat_id=42,
                       retry_delays=(0, 0, 0))
    cfg = BroadcastConfig(skip_if_no_change=False)
    result = await _broadcast_job_wrapper(svc, cfg)

    # wrapper 不返回值；检查副作用
    assert bot.send_message.await_count == 3
    store.log_broadcast.assert_called_once()
    assert store.log_broadcast.call_args.kwargs["success"] is True


# ---------- total failure ----------

async def test_e2e_total_failure_notifies_admin():
    bot, mr, store, cache = _fixtures(side_effects=RuntimeError("down"))
    svc = BroadcastSvc(bot, mr, store, cache, admin_chat_id=42,
                       retry_delays=(0, 0, 0))
    cfg = BroadcastConfig(skip_if_no_change=False)
    await _broadcast_job_wrapper(svc, cfg)

    # 全部尝试 → save_mapping_snapshot 写入 last_error
    assert store.save_mapping_snapshot.called
    saved_mapping = store.save_mapping_snapshot.call_args.args[0]
    assert "无法发送" in (saved_mapping.last_error or "")


# ---------- disabled mapping ----------

async def test_e2e_disabled_mapping_skipped():
    bot, mr, store, cache = _fixtures(enabled=False)
    svc = BroadcastSvc(bot, mr, store, cache, admin_chat_id=42,
                       retry_delays=(0, 0, 0))
    await svc.broadcast_all(skip_if_no_change=False)
    bot.send_message.assert_not_awaited()


# ---------- multiple mappings partial failure ----------

async def test_e2e_partial_failure_with_multiple_mappings():
    bot = MagicMock()
    # 第一个成功，第二个失败
    bot.send_message = AsyncMock(side_effect=[None, RuntimeError("boom"),
                                              RuntimeError("boom"),
                                              RuntimeError("boom"),
                                              RuntimeError("boom")])
    mr = MagicMock()
    mr.load_all = MagicMock(return_value=[
        _mapping("PRJ-001", "100"),
        _mapping("PRJ-002", "200"),
    ])
    store = MagicMock()
    store.latest_successful_broadcast = MagicMock(return_value=None)
    store.log_broadcast = MagicMock()
    store.record_status = MagicMock()
    store.save_mapping_snapshot = MagicMock()
    cache = ProjectCache()
    cache.replace([_project("PRJ-001"), _project("PRJ-002", status=StatusCode.PUBLISHED)])

    svc = BroadcastSvc(bot, mr, store, cache, admin_chat_id=42,
                       retry_delays=(0, 0, 0))
    result = await svc.broadcast_all(skip_if_no_change=False)
    assert result["sent"] == 1
    assert result["failed"] == 1
    # admin notify 调一次
    assert bot.send_message.await_count >= 5  # 2 项目 + 至少 1 admin


# ---------- weekdays_only ----------

async def test_e2e_weekends_skipped():
    bot, mr, store, cache = _fixtures()
    svc = BroadcastSvc(bot, mr, store, cache, admin_chat_id=42,
                       retry_delays=(0, 0, 0))
    cfg = BroadcastConfig(weekdays_only=True)

    # 直接调 wrapper 但 mock datetime；最简方式：把当前时间 fake 成周六
    from unittest.mock import patch
    from src.scheduler import jobs as jobs_mod
    fake_now = datetime(2026, 9, 19, 9, 0, tzinfo=timezone.utc)  # 2026-09-19 是周六
    with patch.object(jobs_mod, "datetime") as FakeDT:
        FakeDT.now.return_value = fake_now
        await _broadcast_job_wrapper(svc, cfg)

    bot.send_message.assert_not_awaited()
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_e2e_broadcast_flow.py -v
```

Expected: FAIL（多数测试因 bot/MR/store 协调而 fail）。

- [ ] **Step 3: 跑测试确认通过**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest tests/test_e2e_broadcast_flow.py -v
```

Expected: 7 passed。如果有 fail，按 traceback 微调 BroadcastSvc / store wiring。

- [ ] **Step 4: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add tests/test_e2e_broadcast_flow.py
git commit -m "feat(phase3): E2E broadcast flow tests covering happy/skip/retry/admin paths"
```

---

## Task 11: README — Phase 3 文档 + main.py 收尾

**Files:**
- Modify: `README.md`
- Modify: `src/main.py`

**Interfaces:**
- 无新增接口
- README 增加 Phase 3 章节（bot token 获取、`config/scheduler.yaml` 模板、test-send 按钮说明）
- `src/main.py` 把 BotService + Scheduler 注入到 `create_app`（lifespan 自动启停）

- [ ] **Step 1: 修改 `src/main.py` —— 注入 BotService + Scheduler**

在 `src/main.py` 现有 `create_app(...)` 调用前后，替换：

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
```

替换为：

```python
    # ========== Phase 2 + Phase 3: 启动 FastUI + Bot + Scheduler ==========
    # 把所有 deps 注入到 FastAPI app
    from src.web.app import create_app
    from src.web.cache import ProjectCache
    from src.web.refresher import BackgroundRefresher
    from src.bot.service import BotService
    from src.bot.broadcast import BroadcastSvc
    from src.scheduler.config import load_scheduler_config
    from src.scheduler.jobs import build_scheduler

    cache = ProjectCache()
    bot_service = BotService()
    broadcast_svc = BroadcastSvc(
        bot_service=bot_service,
        mapping_repo=mapping_repo,
        store=store,
        cache=cache,
        admin_chat_id=int(cfg.admin_chat_id),
        per_status_thresholds=(
            load_scheduler_config(Path("config/scheduler.yaml")).per_status_thresholds
            if Path("config/scheduler.yaml").exists()
            else None
        ),
    )
    scheduler_cfg = load_scheduler_config(Path("config/scheduler.yaml"))
    scheduler = build_scheduler(broadcast_svc, scheduler_cfg)

    app = create_app(
        cfg=cfg,
        store=store,
        sheet_repo=repo,
        mapping_repo=mapping_repo,
        bot_service=bot_service,
        scheduler=scheduler,
        admin_chat_id=int(cfg.admin_chat_id),
    )
    app.state.cache = cache
    app.state.broadcast_svc = broadcast_svc
    app.state.refresher = BackgroundRefresher(repo, mapping_repo, store, cfg, cache)

    print(f"[ui] Listening on http://{cfg.ui_bind}:{cfg.ui_port}")
    print(f"[bot] token={cfg.telegram_bot_token[:6]}... admin={cfg.admin_chat_id}")
    print(f"[scheduler] {len(scheduler_cfg.times)} cron jobs, weekdays_only={scheduler_cfg.weekdays_only}")
```

并把文件顶部 import 改为：

```python
from pathlib import Path
```

（保持 Path 已 import；现有 `argparse` 后已用。）

- [ ] **Step 2: 修改 README.md —— 添加 Phase 3 章节**

在 README 现有 `## Phase 2` 之后插入：

```markdown
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
python -m src.main
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
```

- [ ] **Step 3: 跑全部测试确认无回归**

Run:
```bash
cd "D:/soft/checkGPRobot/.spyproject"
python -m pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 4: 提交**

```bash
cd "D:/soft/checkGPRobot/.spyproject"
git add README.md src/main.py
git commit -m "feat(phase3): wire BotService+Scheduler in main.py and document Phase 3 in README"
```

---

## 验收清单

所有勾选 = Phase 3 完成：

- [ ] T1 依赖装好，bot 子包可 import
- [ ] T2 BotService 通过 getMe 验证 token，start/stop/send_message 工作
- [ ] T3 6 个命令 + admin 权限 gate
- [ ] T4 播报文案含状态/停留/最近流转/责任人/阈值警告
- [ ] T5 BroadcastSvc 实现 skip_if_no_change、1s/2s/4s 重试、admin 告警
- [ ] T6 AsyncIOScheduler cron jobs + 工作日过滤
- [ ] T7 notify_admin 带重试
- [ ] T8 FastAPI lifespan 启停 bot + scheduler
- [ ] T9 test-send 真正调用 bot
- [ ] T10 E2E 测试覆盖 happy/skip/retry/admin
- [ ] T11 main.py 接线 + README 完整

`python -m pytest -v` 全绿，启动后 bot 长连接、scheduler 注册成功、`/help` 回显命令列表。
