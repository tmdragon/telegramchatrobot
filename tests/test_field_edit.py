import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.models.project import Field, Project, SheetView
from src.models.status import StatusCode
from src.sheets.repo import WriteVerificationError
from src.web.app import create_app
from src.web.cache import ProjectCache


def _app():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    app = create_app(cfg, MagicMock(), sheet_repo, mapping_repo, bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    return TestClient(app), app, sheet_repo, cache


def test_field_edit_200_success():
    client, app, sheet_repo, cache = _app()
    sheet_repo.update_cell.return_value = "新值"
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1", sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
                Field(name="备注", value="旧值", column_index=5, row_index=2, recognized_as=None),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    # field_id = "项目主表::项目主表::2::5"
    r = client.put(
        "/api/projects/PRJ-001/fields/%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A2%3A%3A5",
        json={"new_value": "新值"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["value"] == "新值"


def test_field_edit_400_on_locked_field():
    client, app, sheet_repo, cache = _app()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1", sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    # 试图改项目编号 → 400
    r = client.put(
        "/api/projects/PRJ-001/fields/%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A2%3A%3A1",
        json={"new_value": "PRJ-XYZ"},
    )
    assert r.status_code == 400
    assert "locked" in r.json()["detail"].lower() or "锁定" in r.json()["detail"]


def test_field_edit_400_on_empty_value():
    client, app, sheet_repo, cache = _app()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1", sheet_name="项目主表",
            fields=[Field(name="备注", value="OK", column_index=5, row_index=2, recognized_as=None)],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    r = client.put(
        "/api/projects/PRJ-001/fields/%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A2%3A%3A5",
        json={"new_value": "   "},
    )
    assert r.status_code == 400


def test_field_edit_404_on_unknown_project():
    client, app, sheet_repo, cache = _app()
    # Cache populated with PRJ-001 but client requests PUT for PRJ-999 — cold-start
    # 503 guard does not fire (cache non-empty); project-not-found returns 404.
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1", sheet_name="项目主表",
            fields=[Field(name="备注", value="OK", column_index=5, row_index=2, recognized_as=None)],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    r = client.put(
        "/api/projects/PRJ-999/fields/anything::anything::1::1",
        json={"new_value": "x"},
    )
    assert r.status_code == 404


def test_field_edit_409_on_write_verification_error():
    client, app, sheet_repo, cache = _app()
    sheet_repo.update_cell.side_effect = WriteVerificationError(
        "Write verification failed at 项目主表!项目主表 (2,5): wrote '新值', read '旧值'"
    )
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1", sheet_name="项目主表",
            fields=[Field(name="备注", value="旧值", column_index=5, row_index=2, recognized_as=None)],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    r = client.put(
        "/api/projects/PRJ-001/fields/%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A2%3A%3A5",
        json={"new_value": "新值"},
    )
    assert r.status_code == 409
    body = r.json()
    assert body["original_value"] == "旧值"
