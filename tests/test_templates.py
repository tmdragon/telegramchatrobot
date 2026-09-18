from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.web.app import create_app
from src.models.status import StatusCode


def _app():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    return create_app(cfg, MagicMock(), MagicMock(), MagicMock(), bot_service=None)


def test_base_template_renders_with_block():
    app = _app()
    client = TestClient(app)

    @app.get("/_probe_base")
    def _probe():
        from starlette.templating import Jinja2Templates
        templates = app.state.templates
        return templates.TemplateResponse(
            request=MagicMock(),
            name="partials/_status_badge.html",
            context={"code": StatusCode.MAKING, "raw": None},
        )

    # Register the probe route then call
    r = client.get("/_probe_base")
    assert r.status_code == 200
    assert "我方制作中" in r.text
    assert "status-badge" in r.text


def test_status_badge_partial_unknown():
    app = _app()
    client = TestClient(app)

    @app.get("/_probe_unknown")
    def _probe():
        return app.state.templates.TemplateResponse(
            request=MagicMock(),
            name="partials/_status_badge.html",
            context={"code": None, "raw": "未知值"},
        )

    r = client.get("/_probe_unknown")
    assert r.status_code == 200
    assert "未知值" in r.text
    assert "unknown" in r.text


def test_error_banner_partial_renders_messages():
    app = _app()
    client = TestClient(app)

    @app.get("/_probe_error")
    def _probe():
        return app.state.templates.TemplateResponse(
            request=MagicMock(),
            name="partials/_error_banner.html",
            context={"errors": ["Sheets 拉取失败", "快照加载失败"]},
        )

    r = client.get("/_probe_error")
    assert r.status_code == 200
    assert "Sheets 拉取失败" in r.text
    assert "snapshot-error" in r.text or "error-banner" in r.text