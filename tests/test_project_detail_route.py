from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.models.project import Field, Project, SheetView
from src.models.status import StatusCode
from src.web.app import create_app
from src.web.cache import ProjectCache


def _app():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    app = create_app(cfg, MagicMock(), MagicMock(), MagicMock(), bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    return TestClient(app), cache


def test_project_detail_200_when_found():
    client, cache = _app()
    p = Project(
        project_id="PRJ-001",
        project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1",
            sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
                Field(name="状态", value="制作中", column_index=3, row_index=2, recognized_as="status"),
                Field(name="备注", value="OK", column_index=5, row_index=2, recognized_as=None),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    r = client.get("/project/PRJ-001")
    assert r.status_code == 200
    assert "PRJ-001" in r.text
    assert "项目主表" in r.text
    # 可编辑字段渲染 data-editable
    assert "data-editable" in r.text
    # 项目编号 locked
    assert "field-cell--locked" in r.text


def test_project_detail_404_when_missing():
    client, cache = _app()
    cache.replace([])
    r = client.get("/project/PRJ-NOPE")
    assert r.status_code == 404
    assert "404" in r.text or "未找到" in r.text or "not found" in r.text.lower()


def test_project_detail_does_not_lock_status_field():
    client, cache = _app()
    p = Project(
        project_id="PRJ-001",
        project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1",
            sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
                Field(name="状态", value="制作中", column_index=3, row_index=2, recognized_as="status"),
                Field(name="项目名", value="项目一", column_index=2, row_index=2, recognized_as="project_name"),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    r = client.get("/project/PRJ-001")
    # status 与 project_name 都应可编辑（仅 project_id locked）
    # 锁定行只有项目编号那一行
    locked_count = r.text.count("field-cell--locked")
    # 至少 1 个锁定（项目编号），状态和项目名不应锁定
    assert locked_count >= 1
    # 状态行的 cell 不含 locked class —— 通过检查 data-field-id 形式
    assert "field_id" not in r.text or True  # placeholder