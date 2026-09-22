"""Tests for BotService polling resilience: 网络错误不能拖垮 uvicorn。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram.error import NetworkError


@pytest.mark.asyncio
async def test_polling_error_does_not_crash_service():
    """get_updates 抛 NetworkError 时,polling 任务 catch,sleep,重试。"""
    from src.bot.service import BotService

    service = BotService()
    fake_app = MagicMock()
    service._app = fake_app

    call_count = [0]

    async def fake_get_updates(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise NetworkError("test network failure")
        service._shutdown_event.set()
        return []

    fake_app.bot.get_updates = fake_get_updates
    fake_app.process_update = AsyncMock()

    fake_event = asyncio.Event()
    service._shutdown_event = fake_event

    # 用 0.01s backoff 让 test 快速跑完
    polling_task = asyncio.create_task(service._polling_loop(initial_backoff=0.01))
    await asyncio.wait_for(polling_task, timeout=2.0)

    # get_updates 至少被调用了 2 次
    assert call_count[0] >= 2


@pytest.mark.asyncio
async def test_polling_loop_processes_valid_updates():
    """polling_loop 应该把 update 通过 process_update 传给 PTB 的 handler 链。"""
    from src.bot.service import BotService

    service = BotService()
    fake_app = MagicMock()
    service._app = fake_app

    fake_update = MagicMock()
    fake_update.update_id = 42

    async def fake_get_updates(**kwargs):
        service._shutdown_event.set()
        return [fake_update]

    fake_app.bot.get_updates = fake_get_updates
    fake_app.process_update = AsyncMock()

    fake_event = asyncio.Event()
    service._shutdown_event = fake_event

    polling_task = asyncio.create_task(service._polling_loop(initial_backoff=0.01))
    await asyncio.wait_for(polling_task, timeout=2.0)

    fake_app.process_update.assert_called_once_with(fake_update)
    assert service._last_update_id == 42


@pytest.mark.asyncio
async def test_polling_loop_keeps_running_after_multiple_errors():
    """连续多次出错后,polling_loop 仍然存活(只是 backoff 变大)。"""
    from src.bot.service import BotService

    service = BotService()
    fake_app = MagicMock()
    service._app = fake_app

    call_count = [0]

    async def fake_get_updates(**kwargs):
        call_count[0] += 1
        if call_count[0] <= 3:
            raise NetworkError(f"failure {call_count[0]}")
        service._shutdown_event.set()
        return []

    fake_app.bot.get_updates = fake_get_updates
    fake_app.process_update = AsyncMock()

    fake_event = asyncio.Event()
    service._shutdown_event = fake_event

    polling_task = asyncio.create_task(service._polling_loop(initial_backoff=0.01))
    await asyncio.wait_for(polling_task, timeout=5.0)

    assert call_count[0] >= 4