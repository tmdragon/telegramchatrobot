from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.models.project import Field, Project, SheetView
from src.models.status import StatusCode
from src.sheets.mapping_repo import MappingRepo
from src.sheets.repo import SheetRepo
from src.store.db import Store
from src.web.app import create_app
from src.web.cache import ProjectCache


@pytest.fixture
def client_with_cache():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []

    store = MagicMock(spec=Store)
    sheet_repo = MagicMock(spec=SheetRepo)
    mapping_repo = MagicMock(spec=MappingRepo)

    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    return TestClient(app), cache


def test_overview_empty_state_renders_banner(client_with_cache):
    client, cache = client_with_cache
    cache.replace([])  # cold start empty
    store = MagicMock()
    store.load_latest_snapshot.return_value = None
    client.app.state.store = store
    r = client.get("/")
    assert r.status_code == 200
    assert "无法连接 Google Sheets" in r.text or "暂无项目" in r.text


def test_overview_renders_projects(client_with_cache):
    client, cache = client_with_cache
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
    r = client.get("/")
    assert r.status_code == 200
    assert "PRJ-001" in r.text
    assert "我方制作中" in r.text
    assert "项目一" in r.text


def test_overview_links_to_project_detail(client_with_cache):
    client, cache = client_with_cache
    cache.replace([])
    p = Project(
        project_id="PRJ-002",
        project_name=None,
        status=None,
        status_changed_at=None,
        sheets=[],
    )
    cache.replace([p])
    r = client.get("/")
    assert r.status_code == 200
    assert "/project/PRJ-002" in r.text
