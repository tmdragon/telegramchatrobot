from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.models.project import Project
from src.models.status import StatusCode
from src.web.app import create_app
from src.web.cache import ProjectCache


def _make_app():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    store = MagicMock()
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    return TestClient(app), app, cache


def test_api_projects_returns_cache_snapshot():
    client, app, cache = _make_app()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[],
    )
    cache.replace([p])
    r = client.get("/api/projects")
    assert r.status_code == 200
    body = r.json()
    assert body["projects"][0]["project_id"] == "PRJ-001"
    assert body["projects"][0]["status"] == "MAKING"
    assert "last_refresh_at" in body
    assert body["error_count"] == 0


def test_api_projects_503_on_cold_start_empty():
    client, app, cache = _make_app()
    # cache 保持空，Store 也无快照
    app.state.store.load_latest_snapshot.return_value = None
    r = client.get("/api/projects")
    assert r.status_code == 503
    assert "cold start" in r.json()["detail"].lower() or "无法连接" in r.json()["detail"]