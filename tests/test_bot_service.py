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
