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
    # 让 latest_successful_broadcast 返回当前 (status, status_changed_at_iso, message_text)
    p = cache.get("PRJ-001")
    store.latest_successful_broadcast = MagicMock(return_value=(
        p.status.value, p.status_changed_at.isoformat(), "old text"
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
        StatusCode.ORDERED.value, datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc).isoformat(), "old"
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
    # retry_delays 长度 3 → 4 次尝试（首 + 3 重试），再加 notify_admin 4 次
    assert bot_service.send_message.await_count >= 4
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
