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
