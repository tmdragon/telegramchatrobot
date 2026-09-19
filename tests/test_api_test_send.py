"""/api/mappings/{id}/test-send 测试（Phase 3 真正激活）。"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from src.models.project import Field, Mapping, Project, SheetView
from src.models.status import StatusCode
from src.web.app import create_app
from src.web.cache import ProjectCache


def _app_with_bot(bot_service=None):
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    app = create_app(cfg, MagicMock(), MagicMock(), MagicMock(),
                     bot_service=bot_service)
    cache = ProjectCache()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        status_history=[(StatusCode.MAKING, datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc))],
        sheets=[SheetView(
            spreadsheet_id="ss1", sheet_name="项目主表",
            fields=[Field(name="项目编号", value="PRJ-001",
                          column_index=1, row_index=2, recognized_as="project_id")],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    app.state.cache = cache
    mapping_repo = MagicMock()
    mapping_repo.load_all = MagicMock(return_value=[Mapping(
        project_id="PRJ-001", chat_id="123456",
        note="", enabled=True,
        last_broadcast_at=None, last_broadcast_status=None, last_error=None,
    )])
    app.state.mapping_repo = mapping_repo
    return TestClient(app), app


def test_test_send_503_when_no_bot():
    client, _ = _app_with_bot(bot_service=None)
    r = client.post("/api/mappings/PRJ-001/test-send", json={})
    assert r.status_code == 503
    assert "bot" in r.json()["detail"].lower() or "未配置" in r.json()["detail"]


def test_test_send_404_when_no_mapping():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    client, app = _app_with_bot(bot_service=bot)
    app.state.mapping_repo.load_all = MagicMock(return_value=[])
    r = client.post("/api/mappings/PRJ-001/test-send", json={})
    assert r.status_code == 404


def test_test_send_200_calls_bot():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    client, app = _app_with_bot(bot_service=bot)
    r = client.post("/api/mappings/PRJ-001/test-send", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["chat_id"] == "123456"
    assert "PRJ-001" in body["message_preview"]
    bot.send_message.assert_awaited_once()


def test_test_send_502_when_bot_fails():
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))
    client, _ = _app_with_bot(bot_service=bot)
    r = client.post("/api/mappings/PRJ-001/test-send", json={})
    assert r.status_code == 502
    assert "telegram" in r.json()["detail"].lower() or "无法发送" in r.json()["detail"]


def test_test_send_override_chat_id():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    client, _ = _app_with_bot(bot_service=bot)
    r = client.post("/api/mappings/PRJ-001/test-send", json={"chat_id": "999"})
    assert r.status_code == 200
    # bot.send_message 的第一参数
    assert bot.send_message.await_args.args[0] == "999"
