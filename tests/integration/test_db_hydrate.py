"""Tests for Store.hydrate_project_state — 重启后从 project_state 表恢复 status_changed_at。"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.store.db import Store
from src.models.project import Project, SheetView, Field
from src.models.status import StatusCode, normalize


def _make_project(pid: str, status_code: str, fetched_at: datetime) -> Project:
    return Project(
        project_id=pid,
        project_name=f"Project {pid}",
        status=normalize(status_code),
        status_raw=status_code,
        status_changed_at=fetched_at,
        sheets=[
            SheetView(
                spreadsheet_id="ss1",
                sheet_name="工作表1",
                fields=[],
                fetched_at=fetched_at,
            )
        ],
    )


def test_hydrate_overrides_status_changed_at_when_db_has_record(tmp_path: Path):
    """DB 里有项目记录时,hdr 应该用 DB 的 status_changed_at 覆盖 fetch_all 给的 fetched_at。"""
    db = tmp_path / "test.db"
    store = Store(db)
    store.init_schema()

    # DB 中预先有一条历史记录：状态 MAKING,30 天前
    original_changed_at = datetime.now(timezone.utc) - timedelta(days=30)
    store.upsert_project_state("WW-001", "MAKING", original_changed_at)

    # 模拟 fetch_all 返回的 Project(status_changed_at 是 fetched_at = 现在)
    now = datetime.now(timezone.utc)
    p = _make_project("WW-001", "MAKING", now)

    store.hydrate_project_state([p])

    # 状态码没变 → 应该用 DB 的原时间
    assert p.status_changed_at == original_changed_at


def test_hydrate_preserves_status_changed_at_when_status_code_changed(tmp_path: Path):
    """DB 里有项目但状态码变了 → 用 fetch_all 给的新时间,并更新 DB。"""
    db = tmp_path / "test.db"
    store = Store(db)
    store.init_schema()

    old_changed_at = datetime.now(timezone.utc) - timedelta(days=30)
    store.upsert_project_state("WW-001", "MAKING", old_changed_at)

    # 模拟 sheet 拉回来:状态码变成 PUBLISHED,fetched_at = 现在
    now = datetime.now(timezone.utc)
    p = _make_project("WW-001", "PUBLISHED", now)

    store.hydrate_project_state([p])

    # 状态码变了 → 应该用新时间(=now)
    assert p.status_changed_at == now
    # DB 也应该被更新成新状态+新时间
    saved = store.get_project_state("WW-001")
    assert saved[0] == "PUBLISHED"
    assert saved[1] == now


def test_hydrate_writes_new_record_when_db_missing(tmp_path: Path):
    """DB 里没记录 → 写一条新的,用 fetch_all 给的时间。"""
    db = tmp_path / "test.db"
    store = Store(db)
    store.init_schema()

    now = datetime.now(timezone.utc)
    p = _make_project("WW-NEW", "ORDERED", now)

    store.hydrate_project_state([p])

    # DB 应该有这条新记录
    saved = store.get_project_state("WW-NEW")
    assert saved is not None
    assert saved[0] == "ORDERED"
    assert saved[1] == now