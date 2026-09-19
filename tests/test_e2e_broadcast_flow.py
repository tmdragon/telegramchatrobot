"""Phase 3 端到端播报流测试。

模拟 APScheduler 触发 → BroadcastSvc.broadcast_all → 全套依赖的协同。
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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


# ---------- happy path: scheduler wrapper → broadcast_all → sent ----------

async def test_e2e_scheduler_wrapper_triggers_broadcast():
    bot, mr, store, cache = _fixtures()
    svc = BroadcastSvc(bot, mr, store, cache, admin_chat_id=42,
                       retry_delays=(0, 0, 0))
    cfg = BroadcastConfig(times=["09:00", "18:00"], weekdays_only=False,
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
    cfg = BroadcastConfig(skip_if_no_change=False, weekdays_only=False)
    await _broadcast_job_wrapper(svc, cfg)

    # wrapper 不返回值；检查副作用
    assert bot.send_message.await_count == 3
    store.log_broadcast.assert_called_once()
    assert store.log_broadcast.call_args.kwargs["success"] is True


# ---------- total failure ----------

async def test_e2e_total_failure_notifies_admin():
    bot, mr, store, cache = _fixtures(side_effects=RuntimeError("down"))
    svc = BroadcastSvc(bot, mr, store, cache, admin_chat_id=42,
                       retry_delays=(0, 0, 0))
    cfg = BroadcastConfig(skip_if_no_change=False, weekdays_only=False)
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
    # 第一个成功，第二个失败（首 + 3 重试）
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
    # admin notify 调一次（4 次尝试：1 + 3 retry，与默认 retry_delays 一致）
    assert bot.send_message.await_count >= 5  # 1 成功 + 4 失败 + ≥1 admin


# ---------- weekdays_only ----------

async def test_e2e_weekends_skipped():
    bot, mr, store, cache = _fixtures()
    svc = BroadcastSvc(bot, mr, store, cache, admin_chat_id=42,
                       retry_delays=(0, 0, 0))
    cfg = BroadcastConfig(weekdays_only=True)

    # 直接调 wrapper 但 mock datetime；最简方式：把当前时间 fake 成周六
    from src.scheduler import jobs as jobs_mod
    fake_now = datetime(2026, 9, 19, 9, 0, tzinfo=timezone.utc)  # 2026-09-19 是周六
    with patch.object(jobs_mod, "datetime") as FakeDT:
        FakeDT.now.return_value = fake_now
        await _broadcast_job_wrapper(svc, cfg)

    bot.send_message.assert_not_awaited()
