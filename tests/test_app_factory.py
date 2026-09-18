from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.web.app import create_app


def _deps():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    return cfg, MagicMock(), MagicMock(), MagicMock()


def test_create_app_stores_deps_on_state():
    cfg, store, sheet_repo, mapping_repo = _deps()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    assert app.state.cfg is cfg
    assert app.state.store is store
    assert app.state.sheet_repo is sheet_repo
    assert app.state.mapping_repo is mapping_repo
    assert app.state.bot_service is None


def test_create_app_accepts_bot_service_none():
    cfg, store, sheet_repo, mapping_repo = _deps()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    # 404 on unknown route still wires correctly
    client = TestClient(app)
    r = client.get("/does/not/exist")
    assert r.status_code == 404


def test_jinja2_env_autoescape_on():
    cfg, store, sheet_repo, mapping_repo = _deps()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    # Find Jinja2Templates instance via internal state
    from starlette.templating import Jinja2Templates

    # templates should be attached somewhere on the app
    # We expose them via app.state for tests
    env = app.state.templates.env
    assert env.autoescape is True