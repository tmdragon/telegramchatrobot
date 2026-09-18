from datetime import datetime, timezone
from pathlib import Path
import json
from src.store.db import Store
from src.models.project import Mapping


def test_store_init_schema(tmp_path: Path):
    db = Store(tmp_path / "test.db")
    db.init_schema()
    assert (tmp_path / "test.db").exists()


def test_save_and_load_sheet_snapshot(tmp_path: Path):
    db = Store(tmp_path / "test.db")
    db.init_schema()
    rows = [["项目编号", "状态"], ["PRJ-001", "制作中"]]
    ts = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    db.save_sheet_snapshot("ss1", "项目主表", ts, json.dumps(rows, ensure_ascii=False), None)

    loaded = db.load_latest_snapshot("ss1", "项目主表")
    assert loaded is not None
    fetched_at, rows_json, _ = loaded
    assert fetched_at == ts
    assert json.loads(rows_json) == rows


def test_save_and_load_mapping(tmp_path: Path):
    db = Store(tmp_path / "test.db")
    db.init_schema()
    m = Mapping(project_id="PRJ-001", chat_id="-100", note="一群", enabled=True)
    db.save_mapping_snapshot(m)
    loaded = db.load_mapping_snapshots()
    assert len(loaded) == 1
    assert loaded[0].project_id == "PRJ-001"
    assert loaded[0].enabled is True


def test_log_broadcast_and_latest(tmp_path: Path):
    db = Store(tmp_path / "test.db")
    db.init_schema()
    ts1 = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 9, 18, 22, 0, tzinfo=timezone.utc)
    db.log_broadcast("PRJ-001", "-100", "MAKING", "msg1", ts1, True, None)
    db.log_broadcast("PRJ-001", "-100", "CLIENT_REVIEW", "msg2", ts2, True, None)

    latest = db.latest_successful_broadcast("PRJ-001", "-100")
    assert latest is not None
    assert latest[0] == "CLIENT_REVIEW"


def test_record_status(tmp_path: Path):
    db = Store(tmp_path / "test.db")
    db.init_schema()
    ts = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    db.record_status("PRJ-001", "MAKING", ts)
    # 同一时间同一状态重复记录：不应抛错
    db.record_status("PRJ-001", "MAKING", ts)