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


def test_api_project_detail_200_payload_shape():
    client, cache = _app()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1",
            sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
                Field(name="备注", value="OK", column_index=5, row_index=2, recognized_as=None),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    r = client.get("/api/projects/PRJ-001")
    assert r.status_code == 200
    body = r.json()
    assert body["project"]["project_id"] == "PRJ-001"
    sheet = body["project"]["sheets"][0]
    assert sheet["spreadsheet_name"] == "项目主表"
    field = sheet["fields"][0]
    assert field["field_id"] == "项目主表::项目主表::2::1"
    assert field["editable"] is False  # project_id locked
    field2 = sheet["fields"][1]
    assert field2["editable"] is True


def test_api_project_detail_404():
    client, cache = _app()
    cache.replace([])
    r = client.get("/api/projects/PRJ-NOPE")
    assert r.status_code == 404