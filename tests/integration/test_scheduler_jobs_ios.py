"""scheduler jobs 调用 check_app_published 时传 project.platform。

iOS 项目 (project_id 含 'IOS') → platform="ios"；
GP 项目 → platform="gp"。
覆盖三处调用点：_store_monitor_wrapper / trigger_store_check_now / _online_check_one。
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.broadcast import BroadcastSvc
from src.models.project import Project
from src.models.status import StatusCode
from src.scheduler.config import BroadcastConfig
from src.scheduler.jobs import (
    _online_check_one,
    _store_monitor_wrapper,
    trigger_store_check_now,
)
from src.web.cache import ProjectCache


pytestmark = pytest.mark.asyncio


def _ios_project(pid="WW-IOS-001", status=StatusCode.SECOND_REVIEW):
    """iOS 项目（project_id 含 'IOS' → __post_init__ 自动设 platform='ios'）。"""
    return Project(
        project_id=pid,
        project_name="House Raise Up iOS",
        package_name="com.test.ios",
        status=status,
        status_changed_at=datetime(2026, 9, 21, 1, 0, tzinfo=timezone.utc),
        store_url="https://apps.apple.com/app/id12345",
        sheets=[],
    )


def _gp_project(pid="WW-002", status=StatusCode.SECOND_REVIEW):
    """GP 项目（默认 platform='gp'）。"""
    return Project(
        project_id=pid,
        project_name="House Raise Up",
        package_name="com.test",
        status=status,
        status_changed_at=datetime(2026, 9, 21, 1, 0, tzinfo=timezone.utc),
        store_url="https://play.google.com/store/apps/details?id=com.test",
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
    refresher.online_check_schedule = {}
    refresher._find_project_row = MagicMock(return_value=5)

    async def _refresh():
        # 不改 cache 内容；调用方测试的是 check_app_published 调用参数
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
    svc = BroadcastSvc(
        bot_service, mapping_repo, store, cache, admin_chat_id=42,
        retry_delays=(0, 0, 0),
    )
    svc.broadcast_project = AsyncMock(return_value={"sent": 1, "failed": 0, "skipped": 0})
    svc.broadcast_internal_only_with_text = AsyncMock(
        return_value={"sent": 1, "failed": 0, "skipped": 0}
    )
    return svc, bot_service


def _platform_of(mock_check) -> str:
    """从 mock_check.call_args 取 platform (兼容 kwargs/positional)。"""
    args, kwargs = mock_check.call_args
    if "platform" in kwargs:
        return kwargs["platform"]
    # 第 2 个位置参数就是 platform(url 是第 1 个)
    return args[1] if len(args) >= 2 else ""


# ---------- _store_monitor_wrapper ----------

async def test_store_monitor_wrapper_passes_platform_ios_for_ios_project():
    """iOS 项目过 _store_monitor_wrapper 时，check_app_published 收到 platform='ios'。"""
    cache = ProjectCache()
    cache.replace([_ios_project()])
    refresher = _refresher(cache)
    broadcast_svc, _ = _broadcast_svc()

    cfg = BroadcastConfig(store_monitor_min_hours=4, store_monitor_max_hours=8)

    with patch("src.scheduler.jobs.check_app_published",
               new=AsyncMock(return_value={"published": False, "title": None,
                                            "reason": "not_found"})) as mock_check:
        await _store_monitor_wrapper(refresher, broadcast_svc, cfg)

    mock_check.assert_awaited()
    assert _platform_of(mock_check) == "ios", (
        f"iOS 项目应传 platform='ios'，got {_platform_of(mock_check)!r}"
    )


async def test_store_monitor_wrapper_passes_platform_gp_for_gp_project():
    """GP 项目过 _store_monitor_wrapper 时，check_app_published 收到 platform='gp'。"""
    cache = ProjectCache()
    cache.replace([_gp_project()])
    refresher = _refresher(cache)
    broadcast_svc, _ = _broadcast_svc()

    cfg = BroadcastConfig(store_monitor_min_hours=4, store_monitor_max_hours=8)

    with patch("src.scheduler.jobs.check_app_published",
               new=AsyncMock(return_value={"published": False, "title": None,
                                            "reason": "not_found"})) as mock_check:
        await _store_monitor_wrapper(refresher, broadcast_svc, cfg)

    mock_check.assert_awaited()
    assert _platform_of(mock_check) == "gp"


# ---------- trigger_store_check_now ----------

async def test_trigger_store_check_now_passes_platform_ios_for_ios_project():
    """手动监测 iOS 项目时，check_app_published 第二参数为 'ios'。"""
    cache = ProjectCache()
    cache.replace([_ios_project(pid="WW-IOS-MANUAL")])

    refresher = MagicMock()
    refresher.cache = cache
    refresher.sheet_repo = MagicMock()
    refresher.sheet_repo.find_row_by_project_id = MagicMock(return_value=5)
    refresher.sheet_repo.update_cell_by_header = MagicMock()
    refresher.cfg = MagicMock()
    refresher.cfg.spreadsheets = [MagicMock(id="ss1", name="工作表1")]
    refresher._find_project_row = MagicMock(return_value=5)
    refresher.store_check_schedule = {}
    refresher.refresh_now = AsyncMock(
        return_value={"changes": [], "project_count": 1, "per_spreadsheet": []}
    )

    broadcast_svc, _ = _broadcast_svc()
    cfg = BroadcastConfig()

    with patch("src.scheduler.jobs.check_app_published",
               new=AsyncMock(return_value={"published": False, "title": None,
                                            "reason": "not_found"})) as mock_check:
        result = await trigger_store_check_now(
            refresher, broadcast_svc, cfg, "WW-IOS-MANUAL")

    assert result["ok"] is True
    mock_check.assert_awaited()
    assert _platform_of(mock_check) == "ios", (
        f"iOS 项目应传 platform='ios'，got {_platform_of(mock_check)!r}"
    )


async def test_trigger_store_check_now_passes_platform_gp_for_gp_project():
    """手动监测 GP 项目时，check_app_published 第二参数为 'gp'。"""
    cache = ProjectCache()
    cache.replace([_gp_project(pid="WW-GP-MANUAL")])

    refresher = MagicMock()
    refresher.cache = cache
    refresher.sheet_repo = MagicMock()
    refresher.sheet_repo.find_row_by_project_id = MagicMock(return_value=5)
    refresher.sheet_repo.update_cell_by_header = MagicMock()
    refresher.cfg = MagicMock()
    refresher.cfg.spreadsheets = [MagicMock(id="ss1", name="工作表1")]
    refresher._find_project_row = MagicMock(return_value=5)
    refresher.store_check_schedule = {}
    refresher.refresh_now = AsyncMock(
        return_value={"changes": [], "project_count": 1, "per_spreadsheet": []}
    )

    broadcast_svc, _ = _broadcast_svc()
    cfg = BroadcastConfig()

    with patch("src.scheduler.jobs.check_app_published",
               new=AsyncMock(return_value={"published": False, "title": None,
                                            "reason": "not_found"})) as mock_check:
        result = await trigger_store_check_now(
            refresher, broadcast_svc, cfg, "WW-GP-MANUAL")

    assert result["ok"] is True
    mock_check.assert_awaited()
    assert _platform_of(mock_check) == "gp"


# ---------- _online_check_one ----------

async def test_online_check_one_passes_platform_ios_for_ios_project():
    """在架监控 iOS 项目时，check_app_published 收到 platform='ios'。"""
    proj = _ios_project(pid="WW-IOS-PUB", status=StatusCode.PUBLISHED)
    cache = ProjectCache()
    cache.replace([proj])
    refresher = _refresher(cache)
    broadcast_svc, _ = _broadcast_svc()
    cfg = BroadcastConfig()

    with patch("src.scheduler.jobs.check_app_published",
               new=AsyncMock(return_value={"published": True, "title": "App",
                                            "reason": "ok"})) as mock_check:
        await _online_check_one(proj, broadcast_svc, cfg, refresher)

    mock_check.assert_awaited()
    assert _platform_of(mock_check) == "ios", (
        f"iOS 项目应传 platform='ios'，got {_platform_of(mock_check)!r}"
    )


async def test_online_check_one_passes_platform_gp_for_gp_project():
    """在架监控 GP 项目时，check_app_published 收到 platform='gp'。"""
    proj = _gp_project(pid="WW-GP-PUB", status=StatusCode.PUBLISHED)
    cache = ProjectCache()
    cache.replace([proj])
    refresher = _refresher(cache)
    broadcast_svc, _ = _broadcast_svc()
    cfg = BroadcastConfig()

    with patch("src.scheduler.jobs.check_app_published",
               new=AsyncMock(return_value={"published": True, "title": "App",
                                            "reason": "ok"})) as mock_check:
        await _online_check_one(proj, broadcast_svc, cfg, refresher)

    mock_check.assert_awaited()
    assert _platform_of(mock_check) == "gp"