"""scheduler/jobs.py 测试。"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.broadcast import BroadcastSvc
from src.models.project import Project
from src.models.status import StatusCode
from src.scheduler.config import BroadcastConfig
from src.scheduler.jobs import _store_monitor_wrapper, trigger_store_check_now
from src.web.cache import ProjectCache


pytestmark = pytest.mark.asyncio


def _project(pid="WW-002", status=StatusCode.SECOND_REVIEW,
             store_url="https://play.google.com/store/apps/details?id=com.test"):
    return Project(
        project_id=pid,
        project_name="House Raise Up",
        package_name="com.test",
        status=status,
        status_changed_at=datetime(2026, 9, 21, 1, 0, tzinfo=timezone.utc),
        store_url=store_url,
        sheets=[],
    )


def _refresher(cache, sheet_repo=None, cfg=None):
    sheet_repo = sheet_repo or MagicMock()
    sheet_repo.find_row_by_project_id = MagicMock(return_value=5)
    sheet_repo.update_cell_by_header = MagicMock()
    cfg = cfg or MagicMock()
    cfg.spreadsheets = [MagicMock(id="ss1", name="工作表1")]
    refresher = MagicMock()
    refresher.cache = cache
    refresher.sheet_repo = sheet_repo
    refresher.cfg = cfg
    refresher.store_check_schedule = {}
    refresher._find_project_row = MagicMock(return_value=5)
    # refresh_now 替换 cache 中的项目，反映 sheet 刚被改的状态
    async def _refresh():
        cache.replace([_project(status=StatusCode.PUBLISHED,
                                store_url=_project().store_url)])
        return {"changes": [], "project_count": 1, "per_spreadsheet": []}
    refresher.refresh_now = AsyncMock(side_effect=_refresh)
    return refresher


def _broadcast_svc():
    bot_service = MagicMock()
    bot_service.send_message = AsyncMock()
    mapping_repo = MagicMock()
    mapping_repo.load_all = MagicMock(return_value=[])
    store = MagicMock()
    store.latest_successful_broadcast = MagicMock(return_value=None)
    store.log_broadcast = MagicMock()
    store.record_status = MagicMock()
    store.save_mapping_snapshot = MagicMock()
    cache = ProjectCache()
    cache.replace([_project()])
    svc = BroadcastSvc(
        bot_service, mapping_repo, store, cache, admin_chat_id=42,
        retry_delays=(0, 0, 0),
    )
    # 直接 monkeypatch broadcast_project，避开内部细节
    svc.broadcast_project = AsyncMock(return_value={"sent": 1, "failed": 0, "skipped": 0})
    svc.broadcast_internal_only_with_text = AsyncMock(return_value={"sent": 1, "failed": 0, "skipped": 0})
    return svc, bot_service


async def test_store_monitor_wrapper_broadcasts_to_customer_chat_when_published():
    """SECOND_REVIEW → 已上架 时，_store_monitor_wrapper 必须调用 broadcast_project
    通知客户群（不能只发内部群）。这是修复"群里看不到已上架播报"的根因。"""
    cache = ProjectCache()
    cache.replace([_project()])
    refresher = _refresher(cache)
    broadcast_svc, _ = _broadcast_svc()

    cfg = BroadcastConfig(store_monitor_min_hours=4, store_monitor_max_hours=8)

    # 让 check_app_published 返回已上架
    with patch("src.scheduler.jobs.check_app_published",
               new=AsyncMock(return_value={"published": True, "title": "House Raise Up",
                                            "reason": "ok"})):
        await _store_monitor_wrapper(refresher, broadcast_svc, cfg)

    # 关键断言：必须调 broadcast_project（至少 1 次）→ 客户群收到新状态播报
    assert broadcast_svc.broadcast_project.await_count >= 1, (
        "store monitor 必须通知客户群——既已检测到 PUBLISHED，就该发新播报，"
        "否则客户群停留在旧状态（复审中）永远收不到变更通知"
    )
    # 同时 sheet 必须被更新（update_cell_by_header 通过 asyncio.to_thread 异步化，mock 是 sync）
    refresher.sheet_repo.update_cell_by_header.assert_called_once()
    call = refresher.sheet_repo.update_cell_by_header.call_args
    assert call.kwargs.get("new_value") == "已上架" or call.args[-1] == "已上架"


async def test_store_monitor_wrapper_does_not_broadcast_when_still_pending():
    """未上架时（pending），不能误发 publish 播报——只更新下次检查时间。"""
    cache = ProjectCache()
    cache.replace([_project()])
    refresher = _refresher(cache)
    broadcast_svc, _ = _broadcast_svc()

    cfg = BroadcastConfig(store_monitor_min_hours=4, store_monitor_max_hours=8)

    with patch("src.scheduler.jobs.check_app_published",
               new=AsyncMock(return_value={"published": False, "title": None,
                                            "reason": "not_found"})):
        await _store_monitor_wrapper(refresher, broadcast_svc, cfg)

    assert broadcast_svc.broadcast_project.await_count == 0
    refresher.sheet_repo.update_cell_by_header.assert_not_called()
    # 未上架时存了下次重试时间
    assert "WW-002" in refresher.store_check_schedule


# ---------- trigger_store_check_now: 用 refresh 后的新 project 播报 ----------

async def test_trigger_store_check_now_uses_refreshed_project_for_broadcast():
    """手动触发商店检查：检测到已上架后，broadcast_project 必须用 refresh 后的项目
    （status=PUBLISHED, status_raw='已上架'），不能用 refresh 前的旧引用（status=SECOND_REVIEW）。

    这是用户报告的"02:18 状态变更 复审中"误播报的根因——proj 是 refresh_now 之前的引用，
    refresh 后 cache 已经是新对象，但 proj 仍指向旧对象，broadcast 时拿旧 status。"""
    cache = ProjectCache()
    cache.replace([_project()])

    refresher = MagicMock()
    refresher.cache = cache
    refresher.sheet_repo = MagicMock()
    refresher.sheet_repo.find_row_by_project_id = MagicMock(return_value=5)
    refresher.sheet_repo.update_cell_by_header = MagicMock()
    refresher.cfg = MagicMock()
    refresher.cfg.spreadsheets = [MagicMock(id="ss1", name="工作表1")]
    refresher._find_project_row = MagicMock(return_value=5)

    captured: dict = {}

    async def _refresh():
        # 模拟 sheet 已写"已上架"：cache 换成新的 project（PUBLISHED + '已上架'）
        fresh = _project()
        fresh.status = StatusCode.PUBLISHED
        fresh.status_raw = "已上架"
        cache.replace([fresh])
        return {"changes": [], "project_count": 1, "per_spreadsheet": []}

    refresher.refresh_now = AsyncMock(side_effect=_refresh)

    broadcast_svc, _ = _broadcast_svc()
    async def _capture_broadcast(project, **kw):
        captured["status"] = project.status
        captured["status_raw"] = project.status_raw
        return {"sent": 1, "failed": 0, "skipped": 0}
    broadcast_svc.broadcast_project = AsyncMock(side_effect=_capture_broadcast)
    broadcast_svc.broadcast_internal_only_with_text = AsyncMock(
        return_value={"sent": 1, "failed": 0, "skipped": 0})

    cfg_ = BroadcastConfig()

    with patch("src.scheduler.jobs.check_app_published",
               new=AsyncMock(return_value={"published": True, "title": "House Raise Up",
                                            "reason": "ok"})):
        result = await trigger_store_check_now(
            refresher, broadcast_svc, cfg_, "WW-002")

    assert result["ok"] is True
    assert result["published"] is True
    assert broadcast_svc.broadcast_project.await_count >= 1
    # 关键：bcast 的 project 必须是新的（PUBLISHED + status_raw='已上架'），
    # 而不是 refresh 前的旧引用（SECOND_REVIEW + '复审中'）
    assert captured["status"] == StatusCode.PUBLISHED, (
        f"bcast 用了旧 project，仍是 {captured['status']}；"
        f"应在 refresh_now 后从 cache.get 取新对象"
    )
    assert captured["status_raw"] == "已上架"
