"""lifespan 上下文测试：用 fake bot/scheduler 验证 start/stop 调用。"""
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
