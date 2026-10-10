"""gp-packer-server API 端点集成测试。

覆盖:
- 503 when client not configured
- GET /api/projects/{id}/hash 返回缓存(或未缓存)
- POST /api/projects/{id}/refresh-hash 成功/未找到/未配置/服务端错误
- case-insensitive project_id 在 API 层也生效
"""
from __future__ import annotations

import unittest.mock as mock
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.gp_packer import (
    GpPackerAuthError,
    GpPackerClient,
    GpPackerError,
    GpPackerNotFound,
    GpPackerRateLimited,
)
from src.web.app import create_app


def _make_app(client: GpPackerClient | None, store):
    """构造带 mock store + 可选 gp_packer_client 的 FastAPI app。"""
    cfg = mock.MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    sheet_repo = mock.MagicMock()
    mapping_repo = mock.MagicMock()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    app.state.gp_packer_client = client
    return app


# ---------- 503 when not configured ----------

def test_refresh_hash_returns_503_when_client_not_configured():
    store = mock.MagicMock()
    app = _make_app(client=None, store=store)
    r = TestClient(app).post("/api/projects/k1-001/refresh-hash")
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"]


def test_get_hash_works_even_when_client_not_configured():
    """GET 只读缓存,client 不配置时也能读(只是永远空)。"""
    store = mock.MagicMock()
    store.get_gp_packer_hash.return_value = None
    app = _make_app(client=None, store=store)
    r = TestClient(app).get("/api/projects/k1-001/hash")
    assert r.status_code == 200
    body = r.json()
    assert body["cached"] is False
    assert body["project_id"] == "k1-001"


# ---------- GET /api/projects/{id}/hash ----------

def test_get_hash_returns_cached_row():
    store = mock.MagicMock()
    store.get_gp_packer_hash.return_value = {
        "project_id": "k1-001",
        "appid_canonical": "K1-001",
        "jks_sha256": "abc123def456",
        "jks_size": 2139,
        "main_activity": "com.example.M",
        "fetched_at": "2026-10-10T12:00:00+00:00",
        "last_error": None,
    }
    app = _make_app(client=None, store=store)
    r = TestClient(app).get("/api/projects/k1-001/hash")
    assert r.status_code == 200
    body = r.json()
    assert body["cached"] is True
    assert body["jks_sha256"] == "abc123def456"
    assert body["appid_canonical"] == "K1-001"


# ---------- POST /api/projects/{id}/refresh-hash ----------

@pytest.mark.asyncio
async def test_refresh_hash_success_stores_and_returns():
    """200: 调 /info,存 store,返回 hash。"""
    client = mock.MagicMock(spec=GpPackerClient)
    client.resolve_canonical_appid = mock.AsyncMock(return_value="K1-001")
    client.get_info = mock.AsyncMock(return_value={
        "appid": "K1-001",
        "jks_size": 2139,
        "jks_sha256": "abc123def456",
        "main_activity": "com.example.M",
        "properties": "...",
    })
    store = mock.MagicMock()
    app = _make_app(client=client, store=store)
    r = TestClient(app).post("/api/projects/k1-001/refresh-hash")
    assert r.status_code == 200
    body = r.json()
    assert body["jks_sha256"] == "abc123def456"
    assert body["appid_canonical"] == "K1-001"
    # store.upsert_gp_packer_hash 应该被调一次,带正确的 hash
    store.upsert_gp_packer_hash.assert_called_once()
    args, kwargs = store.upsert_gp_packer_hash.call_args
    assert args[0] == "k1-001"  # project_id 是位置参数
    assert kwargs["jks_sha256"] == "abc123def456"
    assert kwargs["appid_canonical"] == "K1-001"


@pytest.mark.asyncio
async def test_refresh_hash_uses_case_insensitive_lookup():
    """用户传 k1-001,内部 resolve 到 K1-001(server 大写),仍能取到 hash。"""
    client = mock.MagicMock(spec=GpPackerClient)
    client.resolve_canonical_appid = mock.AsyncMock(return_value="K1-001")
    client.get_info = mock.AsyncMock(return_value={
        "jks_sha256": "abc",
        "jks_size": 1,
        "main_activity": "x",
    })
    store = mock.MagicMock()
    app = _make_app(client=client, store=store)
    r = TestClient(app).post("/api/projects/k1-001/refresh-hash")
    assert r.status_code == 200
    client.resolve_canonical_appid.assert_awaited_once_with("k1-001")


@pytest.mark.asyncio
async def test_refresh_hash_404_when_project_not_on_server():
    """项目不在 server 上 → 404,last_error 存进 store。"""
    client = mock.MagicMock(spec=GpPackerClient)
    client.resolve_canonical_appid = mock.AsyncMock(return_value=None)  # not found
    store = mock.MagicMock()
    app = _make_app(client=client, store=store)
    r = TestClient(app).post("/api/projects/nonexistent/refresh-hash")
    assert r.status_code == 404
    store.upsert_gp_packer_hash.assert_called_once()
    assert "not found" in (store.upsert_gp_packer_hash.call_args.kwargs.get("last_error") or "")


@pytest.mark.asyncio
async def test_refresh_hash_404_when_gp_packer_raises_not_found():
    """client.get_info 抛 GpPackerNotFound(罕见,resolve_canonical 通常先返回 None)→ 404。"""
    client = mock.MagicMock(spec=GpPackerClient)
    client.resolve_canonical_appid = mock.AsyncMock(return_value="k1-001")
    client.get_info = mock.AsyncMock(side_effect=GpPackerNotFound("appid not found", status=404))
    store = mock.MagicMock()
    app = _make_app(client=client, store=store)
    r = TestClient(app).post("/api/projects/k1-001/refresh-hash")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_refresh_hash_502_on_auth_error():
    """401/403 → 502,last_error 存。"""
    client = mock.MagicMock(spec=GpPackerClient)
    client.resolve_canonical_appid = mock.AsyncMock(side_effect=GpPackerAuthError("invalid token", status=401, detail="invalid token"))
    store = mock.MagicMock()
    app = _make_app(client=client, store=store)
    r = TestClient(app).post("/api/projects/k1-001/refresh-hash")
    assert r.status_code == 502
    assert "auth" in r.json()["detail"].lower() or "invalid" in r.json()["detail"]
    store.upsert_gp_packer_hash.assert_called_once()
    assert "auth" in (store.upsert_gp_packer_hash.call_args.kwargs.get("last_error") or "")


@pytest.mark.asyncio
async def test_refresh_hash_429_on_rate_limit():
    """429 → 429 + last_error 存。"""
    client = mock.MagicMock(spec=GpPackerClient)
    client.resolve_canonical_appid = mock.AsyncMock(side_effect=GpPackerRateLimited("rate limit exceeded", status=429))
    store = mock.MagicMock()
    app = _make_app(client=client, store=store)
    r = TestClient(app).post("/api/projects/k1-001/refresh-hash")
    assert r.status_code == 429
    store.upsert_gp_packer_hash.assert_called_once()
    assert "rate" in (store.upsert_gp_packer_hash.call_args.kwargs.get("last_error") or "")


@pytest.mark.asyncio
async def test_refresh_hash_502_on_generic_gp_packer_error():
    """5xx/网络错误 → 502。"""
    client = mock.MagicMock(spec=GpPackerClient)
    client.resolve_canonical_appid = mock.AsyncMock(side_effect=GpPackerError("server down", status=503, detail="maintenance"))
    store = mock.MagicMock()
    app = _make_app(client=client, store=store)
    r = TestClient(app).post("/api/projects/k1-001/refresh-hash")
    assert r.status_code == 502
    store.upsert_gp_packer_hash.assert_called_once()
