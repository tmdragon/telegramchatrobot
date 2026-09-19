"""BackgroundRefresher diff detection tests.

变化检测：track previous state, return list of changed projects.
首次 refresh 不算变化（避免重启后立刻全员播报）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.project import Project
from src.models.status import StatusCode
from src.web.cache import ProjectCache
from src.web.refresher import BackgroundRefresher


def _make_project(pid: str, status=StatusCode.MAKING, status_changed_at=None) -> Project:
    return Project(
        project_id=pid, project_name=f"项目{pid}", status=status,
        status_changed_at=status_changed_at or datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
        status_history=[(status, status_changed_at or datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc))],
        sheets=[],
    )


def _make_refresher(sheet_repo, mapping_repo, store, cfg, cache) -> BackgroundRefresher:
    return BackgroundRefresher(sheet_repo, mapping_repo, store, cfg, cache)


async def _refresh(refresher, projects: list[Project]) -> dict:
    """调 refresher.refresh_now() 并 mock sheet_repo.fetch_all 返回给定 projects。"""
    refresher.sheet_repo.fetch_all = MagicMock(return_value=projects)
    refresher.sheet_repo.client.open = MagicMock()
    refresher.sheet_repo.client.open.return_value.worksheet = MagicMock(
        return_value=MagicMock(get_all_values=MagicMock(return_value=[]))
    )
    return await refresher.refresh_now()


@pytest.mark.asyncio
async def test_first_refresh_returns_no_changes():
    """首次 refresh：填 cache，但不返回 changes（避免启动后立刻全员播报）。"""
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    store = MagicMock()
    cfg = MagicMock()
    cfg.spreadsheets = [MagicMock(id="ss1", name="项目主表")]
    cache = ProjectCache()
    refresher = _make_refresher(sheet_repo, mapping_repo, store, cfg, cache)

    result = await _refresh(refresher, [_make_project("PRJ-001"), _make_project("PRJ-002")])
    assert result["is_first_refresh"] is True
    assert result["changes"] == []
    # cache 应已填
    assert cache.get("PRJ-001") is not None
    assert cache.get("PRJ-002") is not None


@pytest.mark.asyncio
async def test_second_refresh_with_no_changes_returns_empty():
    """无变化的二次 refresh：changes 为空。"""
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    store = MagicMock()
    cfg = MagicMock()
    cfg.spreadsheets = [MagicMock(id="ss1", name="项目主表")]
    cache = ProjectCache()
    refresher = _make_refresher(sheet_repo, mapping_repo, store, cfg, cache)

    p1 = _make_project("PRJ-001")
    p2 = _make_project("PRJ-002")
    await _refresh(refresher, [p1, p2])

    # 第二次拉同样数据
    p1b = _make_project("PRJ-001")
    p2b = _make_project("PRJ-002")
    result = await _refresh(refresher, [p1b, p2b])
    assert result["is_first_refresh"] is False
    assert result["changes"] == []


@pytest.mark.asyncio
async def test_status_code_change_is_detected():
    """status_code 从 MAKING → CLIENT_REVIEW 视为变化。"""
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    store = MagicMock()
    cfg = MagicMock()
    cfg.spreadsheets = [MagicMock(id="ss1", name="项目主表")]
    cache = ProjectCache()
    refresher = _make_refresher(sheet_repo, mapping_repo, store, cfg, cache)

    await _refresh(refresher, [_make_project("PRJ-001", status=StatusCode.MAKING)])

    # 第二次：status 变了
    p_changed = _make_project("PRJ-001", status=StatusCode.CLIENT_REVIEW)
    result = await _refresh(refresher, [p_changed])
    assert len(result["changes"]) == 1
    assert result["changes"][0].project_id == "PRJ-001"
    assert result["changes"][0].status == StatusCode.CLIENT_REVIEW


@pytest.mark.asyncio
async def test_status_changed_at_change_alone_is_not_detected():
    """status_changed_at 单独变化（同 code）不算变化 —— 因为 SheetRepo 每次刷新
    重建 dict 时都会把 status_changed_at 重写为 fetched_at，会造成误判。
    只比 status 码。"""
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    store = MagicMock()
    cfg = MagicMock()
    cfg.spreadsheets = [MagicMock(id="ss1", name="项目主表")]
    cache = ProjectCache()
    refresher = _make_refresher(sheet_repo, mapping_repo, store, cfg, cache)

    old_time = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    await _refresh(refresher, [_make_project("PRJ-001", status=StatusCode.MAKING,
                                              status_changed_at=old_time)])

    # 第二次：同一 status，但时间戳变了（模拟 SheetRepo 重建 dict 重写时间）
    new_time = datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)
    p_changed = _make_project("PRJ-001", status=StatusCode.MAKING,
                              status_changed_at=new_time)
    result = await _refresh(refresher, [p_changed])
    assert result["changes"] == []


@pytest.mark.asyncio
async def test_new_project_is_detected():
    """新增项目（之前不存在）算变化。"""
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    store = MagicMock()
    cfg = MagicMock()
    cfg.spreadsheets = [MagicMock(id="ss1", name="项目主表")]
    cache = ProjectCache()
    refresher = _make_refresher(sheet_repo, mapping_repo, store, cfg, cache)

    await _refresh(refresher, [_make_project("PRJ-001")])

    # 第二次：多了一个项目
    result = await _refresh(refresher, [
        _make_project("PRJ-001"),
        _make_project("PRJ-002"),  # new
    ])
    assert len(result["changes"]) == 1
    assert result["changes"][0].project_id == "PRJ-002"


@pytest.mark.asyncio
async def test_multiple_changes_in_one_refresh():
    """同一次 refresh 内多个项目变化，全部返回。"""
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    store = MagicMock()
    cfg = MagicMock()
    cfg.spreadsheets = [MagicMock(id="ss1", name="项目主表")]
    cache = ProjectCache()
    refresher = _make_refresher(sheet_repo, mapping_repo, store, cfg, cache)

    await _refresh(refresher, [
        _make_project("PRJ-001", status=StatusCode.MAKING),
        _make_project("PRJ-002", status=StatusCode.MAKING),
        _make_project("PRJ-003", status=StatusCode.MAKING),
    ])

    # 第二次：001 变了、002 不变、003 变了
    result = await _refresh(refresher, [
        _make_project("PRJ-001", status=StatusCode.CLIENT_REVIEW),  # changed
        _make_project("PRJ-002", status=StatusCode.MAKING),       # same
        _make_project("PRJ-003", status=StatusCode.PUBLISHED),     # changed
    ])
    changed_ids = sorted(p.project_id for p in result["changes"])
    assert changed_ids == ["PRJ-001", "PRJ-003"]