from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.web.app import create_app


def _fake_deps():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    store = MagicMock()
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    return cfg, store, sheet_repo, mapping_repo


def test_health_returns_ok():
    cfg, store, sheet_repo, mapping_repo = _fake_deps()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}