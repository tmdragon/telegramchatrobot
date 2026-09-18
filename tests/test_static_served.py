from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.web.app import create_app


def test_static_css_served():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    app = create_app(cfg, MagicMock(), MagicMock(), MagicMock(), bot_service=None)
    client = TestClient(app)
    r = client.get("/static/css/app.css")
    assert r.status_code == 200
    assert "status-bar" in r.text


def test_static_js_served():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    app = create_app(cfg, MagicMock(), MagicMock(), MagicMock(), bot_service=None)
    client = TestClient(app)
    r = client.get("/static/js/api.js")
    assert r.status_code == 200
    assert "ApiError" in r.text