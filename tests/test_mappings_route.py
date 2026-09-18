from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.models.project import Mapping
from src.web.app import create_app


def _app():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    mapping_repo = MagicMock()
    mapping_repo.load_all.return_value = [
        Mapping(
            project_id="PRJ-001", chat_id="-100123", note="一群",
            enabled=True,
            last_broadcast_at=datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc),
            last_broadcast_status="ok", last_error=None,
        ),
        Mapping(
            project_id="PRJ-002", chat_id="-100456", note="二群",
            enabled=False,
            last_broadcast_at=None, last_broadcast_status=None, last_error=None,
        ),
    ]
    app = create_app(cfg, MagicMock(), MagicMock(), mapping_repo, bot_service=None)
    return TestClient(app), app


def test_mappings_route_200():
    client, app = _app()
    r = client.get("/mappings")
    assert r.status_code == 200
    assert "PRJ-001" in r.text
    assert "PRJ-002" in r.text
    assert "一群" in r.text


def test_mappings_route_has_modal_partials():
    client, app = _app()
    r = client.get("/mappings")
    assert r.status_code == 200
    assert "_mapping_modal" in r.text or "_mapping_modal.html" in r.text or "mapping-modal" in r.text
    assert "_confirm_dialog" in r.text or "confirm-dialog" in r.text