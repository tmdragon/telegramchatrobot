"""端到端集成测试：启动一个完整 FastAPI 应用，跑遍核心流程。"""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.config import SpreadsheetConfig
from src.models.project import Field, Mapping, Project, SheetView
from src.models.status import StatusCode
from src.web.app import create_app


def _make_full_app(tmp_path: Path) -> TestClient:
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = [
        SpreadsheetConfig(id="ss1", name="项目主表", role="master"),
    ]

    store = MagicMock()
    # 默认 Store 空快照 → /api/projects 期望 503
    store.load_latest_snapshot.return_value = None

    sheet_repo = MagicMock()
    sheet_repo.update_cell.return_value = "新值"

    mapping_repo = MagicMock()
    mapping_repo.load_all.return_value = []
    mapping_repo.delete.return_value = None

    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    from src.web.cache import ProjectCache
    cache = ProjectCache()
    app.state.cache = cache
    return TestClient(app)


def test_e2e_get_overview_returns_200(tmp_path: Path):
    client = _make_full_app(tmp_path)
    r = client.get("/")
    assert r.status_code == 200


def test_e2e_get_health_returns_ok(tmp_path: Path):
    client = _make_full_app(tmp_path)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_e2e_static_assets_served(tmp_path: Path):
    client = _make_full_app(tmp_path)
    r = client.get("/static/css/app.css")
    assert r.status_code == 200
    assert "status-bar" in r.text


def test_e2e_api_projects_503_on_cold_start(tmp_path: Path):
    client = _make_full_app(tmp_path)
    r = client.get("/api/projects")
    assert r.status_code == 503


def test_e2e_full_flow_with_cached_projects(tmp_path: Path):
    client = _make_full_app(tmp_path)
    app = client.app

    # hydrate cache
    from src.web.cache import ProjectCache
    cache: ProjectCache = app.state.cache
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1", sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
                Field(name="状态", value="制作中", column_index=3, row_index=2, recognized_as="status"),
                Field(name="备注", value="旧值", column_index=5, row_index=2, recognized_as=None),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])

    # /api/projects
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json()["projects"][0]["project_id"] == "PRJ-001"

    # /api/projects/PRJ-001
    r = client.get("/api/projects/PRJ-001")
    assert r.status_code == 200
    body = r.json()
    sheet = body["project"]["sheets"][0]
    # project_id 字段不可编辑
    pid_field = next(f for f in sheet["fields"] if f["recognized_as"] == "project_id")
    assert pid_field["editable"] is False

    # PUT locked field → 400
    encoded = "%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A2%3A%3A1"
    r = client.put(f"/api/projects/PRJ-001/fields/{encoded}", json={"new_value": "X"})
    assert r.status_code == 400

    # PUT editable field → 200
    encoded = "%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A%E9%A1%B9%E7%9B%AE%E4%B8%BB%E8%A1%A8%3A%3A2%3A%3A5"
    r = client.put(f"/api/projects/PRJ-001/fields/{encoded}", json={"new_value": "新值"})
    assert r.status_code == 200

    # /mappings HTML
    r = client.get("/mappings")
    assert r.status_code == 200

    # POST /api/mappings → 201
    r = client.post("/api/mappings", json={
        "project_id": "PRJ-X", "chat_id": "-100", "note": "", "enabled": True,
    })
    assert r.status_code == 201


def test_e2e_404_on_unknown_project(tmp_path: Path):
    client = _make_full_app(tmp_path)
    r = client.get("/project/PRJ-NOPE")
    assert r.status_code == 404