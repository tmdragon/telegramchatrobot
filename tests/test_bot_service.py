"""BotService 单元测试：用 AsyncMock 注入假 Application + Bot。

覆盖两阶段生命周期：init(token) → register_handlers(app) → start_polling()。
保留 start(token) 作为 backward-compat shim。
"""
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


# ---------- init() ----------

async def test_init_builds_app_and_validates_token():
    """init() 应只构造 Application + 验证 token，不触发 initialize/start/polling。"""
    svc = BotService()
    app, bot = _fake_app_and_bot(me_username="my_bot")
    with patch("src.bot.service.Application") as AppCls:
        builder = MagicMock()
        builder.token.return_value = builder
        builder.build.return_value = app
        AppCls.builder.return_value = builder
        await svc.init("123:ABC")

    bot.get_me.assert_awaited_once()
    assert svc.username == "my_bot"
    # init() 不应触发 initialize / start / start_polling
    app.initialize.assert_not_awaited()
    app.start.assert_not_awaited()
    app.updater.start_polling.assert_not_awaited()


async def test_init_raises_on_invalid_token():
    """getMe 失败 → RuntimeError 向上抛；polling 必须没被触发。"""
    svc = BotService()
    app, bot = _fake_app_and_bot()
    bot.get_me = AsyncMock(side_effect=RuntimeError("Unauthorized"))
    with patch("src.bot.service.Application") as AppCls:
        builder = MagicMock()
        builder.token.return_value = builder
        builder.build.return_value = app
        AppCls.builder.return_value = builder
        with pytest.raises(RuntimeError, match="Unauthorized"):
            await svc.init("BAD_TOKEN")
    app.initialize.assert_not_awaited()
    app.updater.start_polling.assert_not_awaited()


# ---------- start_polling() ----------

async def test_start_polling_initializes_and_starts():
    """start_polling() 应按顺序调 initialize → start → start_polling(drop_pending_updates=True)。"""
    svc = BotService()
    app, bot = _fake_app_and_bot()
    with patch("src.bot.service.Application") as AppCls:
        builder = MagicMock()
        builder.token.return_value = builder
        builder.build.return_value = app
        AppCls.builder.return_value = builder
        await svc.init("ok")
        await svc.start_polling()

    app.initialize.assert_awaited_once()
    app.start.assert_awaited_once()
    app.updater.start_polling.assert_awaited_once()
    assert app.updater.start_polling.await_args.kwargs.get("drop_pending_updates") is True


async def test_start_polling_requires_init():
    """未 init() 就 start_polling() → RuntimeError。"""
    svc = BotService()
    with pytest.raises(RuntimeError, match="init"):
        await svc.start_polling()


# ---------- start() backward-compat shim ----------

async def test_start_is_backward_compat_shim():
    """start(token) = init() + start_polling() 一气呵成。"""
    svc = BotService()
    app, bot = _fake_app_and_bot()
    with patch("src.bot.service.Application") as AppCls:
        builder = MagicMock()
        builder.token.return_value = builder
        builder.build.return_value = app
        AppCls.builder.return_value = builder
        await svc.start("ok")

    bot.get_me.assert_awaited_once()
    app.initialize.assert_awaited_once()
    app.start.assert_awaited_once()
    app.updater.start_polling.assert_awaited_once()


# ---------- stop() ----------

async def test_stop_reverses_start_polling_order():
    """stop() 应反向关闭：stop_polling → app.stop → app.shutdown。"""
    svc = BotService()
    app, bot = _fake_app_and_bot()
    with patch("src.bot.service.Application") as AppCls:
        builder = MagicMock()
        builder.token.return_value = builder
        builder.build.return_value = app
        AppCls.builder.return_value = builder
        await svc.init("ok")
        await svc.start_polling()

    await svc.stop()
    app.updater.stop_polling.assert_awaited_once()
    app.stop.assert_awaited_once()
    app.shutdown.assert_awaited_once()


# ---------- send_message() ----------

async def test_send_message_calls_bot():
    svc = BotService()
    app, bot = _fake_app_and_bot()
    with patch("src.bot.service.Application") as AppCls:
        builder = MagicMock()
        builder.token.return_value = builder
        builder.build.return_value = app
        AppCls.builder.return_value = builder
        await svc.init("ok")
        await svc.start_polling()

    await svc.send_message(123456, "hello")
    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 123456
    assert kwargs["text"] == "hello"


# ---------- getters ----------

async def test_get_chat_id_hint_returns_none_before_any_update():
    svc = BotService()
    assert await svc.get_chat_id_hint() is None


async def test_username_none_before_start():
    svc = BotService()
    assert svc.username is None