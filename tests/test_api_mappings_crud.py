from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.models.project import Mapping
from src.web.app import create_app


@pytest.fixture
def client_with_repo():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    mapping_repo = MagicMock()
    mapping_repo.load_all.return_value = [
        Mapping(project_id="PRJ-001", chat_id="-100123", note="一群", enabled=True,
                last_broadcast_at=datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc),
                last_broadcast_status="ok", last_error=None),
    ]
    store = MagicMock()
    app = create_app(cfg, store, MagicMock(), mapping_repo, bot_service=None)
    return TestClient(app), store, mapping_repo


def test_get_mappings_returns_list(client_with_repo):
    client, _, _ = client_with_repo
    r = client.get("/api/mappings")
    assert r.status_code == 200
    body = r.json()
    assert len(body["mappings"]) == 1
    assert body["mappings"][0]["project_id"] == "PRJ-001"


def test_post_mappings_creates(client_with_repo):
    client, store, mapping_repo = client_with_repo
    mapping_repo.load_all.return_value = []  # 不重复
    r = client.post("/api/mappings", json={
        "project_id": "PRJ-002", "chat_id": "-100456", "note": "二群", "enabled": True,
    })
    assert r.status_code == 201
    assert r.json()["project_id"] == "PRJ-002"
    mapping_repo.upsert.assert_called_once()
    store.save_mapping_snapshot.assert_called_once()


def test_post_mappings_400_on_duplicate(client_with_repo):
    client, _, _ = client_with_repo
    r = client.post("/api/mappings", json={
        "project_id": "PRJ-001", "chat_id": "-100999", "note": "", "enabled": True,
    })
    assert r.status_code == 400
    assert "duplicate" in r.json()["detail"].lower() or "已存在" in r.json()["detail"]


def test_post_mappings_400_on_bad_chat_id(client_with_repo):
    client, _, _ = client_with_repo
    r = client.post("/api/mappings", json={
        "project_id": "PRJ-003", "chat_id": "abc", "note": "", "enabled": True,
    })
    assert r.status_code == 400


def test_post_mappings_400_on_empty_project_id(client_with_repo):
    client, _, _ = client_with_repo
    r = client.post("/api/mappings", json={
        "project_id": "", "chat_id": "-100", "note": "", "enabled": True,
    })
    assert r.status_code == 400


def test_put_mappings_updates(client_with_repo):
    client, store, mapping_repo = client_with_repo
    mapping_repo.load_all.return_value = [
        Mapping(project_id="PRJ-001", chat_id="-100123", note="一群", enabled=True,
                last_broadcast_at=datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc),
                last_broadcast_status="ok", last_error=None),
    ]
    r = client.put("/api/mappings/PRJ-001", json={"note": "新备注", "enabled": False})
    assert r.status_code == 200
    body = r.json()
    assert body["note"] == "新备注"
    assert body["enabled"] is False
    # last_broadcast_at 应保留
    assert body["last_broadcast_at"] == "2026-09-18T21:00:00+00:00"
    mapping_repo.upsert.assert_called_once()


def test_delete_mappings_soft(client_with_repo):
    client, _, mapping_repo = client_with_repo
    r = client.delete("/api/mappings/PRJ-001")
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == "PRJ-001"
    assert body["enabled"] is False
    mapping_repo.delete.assert_called_once_with("PRJ-001")