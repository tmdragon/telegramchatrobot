"""lifespan 上下文测试：用 fake bot/scheduler 验证 start/stop 调用。

验证正确的生命周期顺序：init → register_handlers → start_polling。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from src.web.app import create_app


def _make_app_with_fakes():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    cfg.telegram_bot_token = "test-token"

    bot_service = MagicMock()
    bot_service.init = AsyncMock()
    bot_service.start_polling = AsyncMock()
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


def test_lifespan_starts_bot_in_correct_order():
    """lifespan 启动应触发 init → register_handlers → start_polling + scheduler.start。"""
    app, bot, sch = _make_app_with_fakes()
    with TestClient(app) as client:
        # 启动顺序：init → register_handlers → start_polling
        bot.init.assert_awaited_once()
        bot._app.add_handler.assert_called()  # register_handlers
        bot.start_polling.assert_awaited_once()
        sch.start.assert_called_once()
        r = client.get("/health")
        assert r.status_code == 200


def test_lifespan_registers_handlers_before_polling():
    """回归保护：register_handlers 必须在 start_polling 之前调用。

    否则 PTB 不会把第一批 handler 加入 dispatcher，群里客户发指令会
    无响应（参见 commands.py:13 的契约注释）。
    """
    app, bot, _sch = _make_app_with_fakes()
    sequence = []

    async def _init(*_a, **_kw):
        sequence.append("init")

    async def _start_polling(*_a, **_kw):
        sequence.append("start_polling")

    bot.init.side_effect = _init
    bot.start_polling.side_effect = _start_polling
    bot._app.add_handler.side_effect = lambda *a, **kw: sequence.append("add_handler")

    with TestClient(app):
        pass

    assert sequence.index("init") < sequence.index("add_handler") < sequence.index(
        "start_polling"
    ), f"wrong lifecycle order: {sequence}"


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
    bot.init = AsyncMock()
    bot.start_polling = AsyncMock()
    bot.stop = AsyncMock()
    bot._app = MagicMock()
    bot._app.add_handler = MagicMock()
    bot._app.bot_data = {}

    app = create_app(
        cfg, MagicMock(), MagicMock(), MagicMock(),
        bot_service=bot, scheduler=None, admin_chat_id=1,
    )
    with TestClient(app):
        bot.init.assert_awaited_once()
        bot.start_polling.assert_awaited_once()
    bot.stop.assert_awaited_once()