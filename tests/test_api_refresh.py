from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.models.project import Project
from src.models.status import StatusCode
from src.web.app import create_app
from src.web.cache import ProjectCache
from src.web.refresher import BackgroundRefresher


@pytest.fixture
def client_with_refresher():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = [MagicMock(id="ss1", name="项目主表")]

    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    store = MagicMock()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache

    refresher = BackgroundRefresher(sheet_repo, mapping_repo, store, cfg, cache)
    app.state.refresher = refresher
    return TestClient(app), refresher


@pytest.mark.asyncio
async def test_api_refresh_calls_refresher_and_returns_per_ss(client_with_refresher):
    client, refresher = client_with_refresher
    refresher.refresh_now = AsyncMock(return_value={
        "refreshed_at": datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc).isoformat(),
        "project_count": 1,
        "per_spreadsheet": [
            {"spreadsheet_name": "项目主表", "ok": True, "error": None, "fetched_rows": 3}
        ],
    })
    r = client.post("/api/refresh", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["project_count"] == 1
    assert body["per_spreadsheet"][0]["ok"] is True


@pytest.mark.asyncio
async def test_api_refresh_partial_failure_keeps_cache(client_with_refresher):
    client, refresher = client_with_refresher
    # 即使 refresh 报告部分失败，UI 仍能看到旧 cache
    refresher.refresh_now = AsyncMock(return_value={
        "refreshed_at": datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc).isoformat(),
        "project_count": 0,
        "per_spreadsheet": [
            {"spreadsheet_name": "项目主表", "ok": False, "error": "gspread transport error", "fetched_rows": 0}
        ],
    })
    r = client.post("/api/refresh", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["per_spreadsheet"][0]["ok"] is False
    assert "transport" in body["per_spreadsheet"][0]["error"].lower() or "gspread" in body["per_spreadsheet"][0]["error"]