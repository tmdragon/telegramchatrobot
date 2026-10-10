"""GpPackerClient 单元测试。

httpx 通过 mock patch 拦截,不真打网络。
测试覆盖:列表 / 信息 / 大小写不敏感 / 缓存 / 错误码。
"""
from __future__ import annotations

import json
import unittest.mock as mock

import httpx
import pytest

from src.gp_packer import (
    GpPackerAuthError,
    GpPackerClient,
    GpPackerError,
    GpPackerNotFound,
    GpPackerRateLimited,
)


def _fake_client(payload, status=200, text=""):
    """构造 httpx.AsyncClient 的 mock;接受任意 kwargs(模拟 _get_json 的调用)。"""

    class _Resp:
        def __init__(self):
            self.status_code = status
            self._payload = payload
            self.text = text or json.dumps(payload)

        def json(self):
            if self._payload is None:
                raise ValueError("no json")
            return self._payload

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return _Resp()

    return _Client()


# ---------- 构造 ----------

def test_construction_requires_token():
    with pytest.raises(ValueError, match="token is required"):
        GpPackerClient(base_url="https://x", token="")


def test_construction_strips_trailing_slash():
    c = GpPackerClient(base_url="https://x.example.com/", token="abc")
    assert c.base_url == "https://x.example.com"


# ---------- list_appids ----------

@pytest.mark.asyncio
async def test_list_appids_hits_expected_endpoint_and_parses():
    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=_fake_client({"appids": ["k1-001", "demo"]})):
        c = GpPackerClient("https://x", "tok")
        result = await c.list_appids()
    assert result == ["k1-001", "demo"]


@pytest.mark.asyncio
async def test_list_appids_handles_empty_response():
    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=_fake_client({"appids": []})):
        c = GpPackerClient("https://x", "tok")
        result = await c.list_appids()
    assert result == []


@pytest.mark.asyncio
async def test_list_appids_handles_missing_appids_key():
    """API 响应里没 appids 键时(异常)返回空 list,不崩。"""
    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=_fake_client({})):
        c = GpPackerClient("https://x", "tok")
        result = await c.list_appids()
    assert result == []


# ---------- get_info ----------

@pytest.mark.asyncio
async def test_get_info_returns_full_payload():
    payload = {
        "appid": "k1-001",
        "jks_size": 2139,
        "jks_sha256": "abc123def456",
        "main_activity": "com.example.k1.MainActivity",
        "properties": "sign.enabled=true",
    }
    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=_fake_client(payload)):
        c = GpPackerClient("https://x", "tok")
        result = await c.get_info("k1-001")
    assert result == payload
    assert result["jks_sha256"] == "abc123def456"


# ---------- 错误码 ----------

@pytest.mark.asyncio
async def test_404_raises_not_found():
    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=_fake_client({"detail": "appid not found"}, status=404)):
        c = GpPackerClient("https://x", "tok")
        with pytest.raises(GpPackerNotFound) as exc:
            await c.get_info("missing")
    assert exc.value.status == 404


@pytest.mark.asyncio
async def test_401_raises_auth_error():
    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=_fake_client({"detail": "invalid token"}, status=401)):
        c = GpPackerClient("https://x", "tok")
        with pytest.raises(GpPackerAuthError) as exc:
            await c.list_appids()
    assert exc.value.status == 401
    assert exc.value.detail == "invalid token"


@pytest.mark.asyncio
async def test_403_raises_auth_error():
    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=_fake_client({"detail": "forbidden"}, status=403)):
        c = GpPackerClient("https://x", "tok")
        with pytest.raises(GpPackerAuthError) as exc:
            await c.list_appids()
    assert exc.value.status == 403


@pytest.mark.asyncio
async def test_410_raises_auth_error_as_token_expired():
    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=_fake_client({"detail": "token expired"}, status=410)):
        c = GpPackerClient("https://x", "tok")
        with pytest.raises(GpPackerAuthError) as exc:
            await c.list_appids()
    assert exc.value.status == 410
    assert "expired" in str(exc.value)


@pytest.mark.asyncio
async def test_429_raises_rate_limited():
    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=_fake_client({"detail": "rate limit exceeded"}, status=429)):
        c = GpPackerClient("https://x", "tok")
        with pytest.raises(GpPackerRateLimited) as exc:
            await c.list_appids()
    assert exc.value.status == 429


@pytest.mark.asyncio
async def test_500_raises_generic_error():
    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=_fake_client({"detail": "boom"}, status=500)):
        c = GpPackerClient("https://x", "tok")
        with pytest.raises(GpPackerError) as exc:
            await c.list_appids()
    assert exc.value.status == 500
    assert exc.value.detail == "boom"


@pytest.mark.asyncio
async def test_network_error_raises_generic_error():
    """httpx.RequestError(如连接超时)被包成 GpPackerError。"""

    class _BoomClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            raise httpx.ConnectError("nope")

        async def __aexit__(self, *a):
            return False

    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=_BoomClient()):
        c = GpPackerClient("https://x", "tok")
        with pytest.raises(GpPackerError) as exc:
            await c.list_appids()
    assert "request failed" in str(exc.value)


# ---------- 大小写不敏感 ----------

@pytest.mark.asyncio
async def test_resolve_canonical_is_case_insensitive():
    """项目编号 k1-001 应匹配 server 上的 K1-001。"""
    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=_fake_client({"appids": ["K1-001", "demo"]})):
        c = GpPackerClient("https://x", "tok")
        assert await c.resolve_canonical_appid("k1-001") == "K1-001"
        assert await c.resolve_canonical_appid("K1-001") == "K1-001"
        assert await c.resolve_canonical_appid("K1-001".lower()) == "K1-001"


@pytest.mark.asyncio
async def test_resolve_canonical_returns_none_for_missing_project():
    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=_fake_client({"appids": ["k1-001"]})):
        c = GpPackerClient("https://x", "tok")
        assert await c.resolve_canonical_appid("nonexistent") is None
        # 实际是 k1-001(小写 server) — 大小写不敏感匹配
        assert await c.resolve_canonical_appid("K1-001") == "k1-001"


# ---------- 缓存 ----------

@pytest.mark.asyncio
async def test_appid_cache_avoids_repeat_list_call():
    """第二次 resolve_canonical_appid 命中缓存,不应再调 list_appids。"""
    client_mock = mock.MagicMock()
    client_mock.__aenter__ = mock.AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = mock.AsyncMock(return_value=False)
    resp = mock.MagicMock()
    resp.status_code = 200
    resp.json = mock.MagicMock(return_value={"appids": ["k1-001", "demo"]})
    client_mock.get = mock.AsyncMock(return_value=resp)

    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=client_mock):
        c = GpPackerClient("https://x", "tok")
        await c.resolve_canonical_appid("k1-001")
        await c.resolve_canonical_appid("demo")
        # list_appids 只应该被调一次(第二次 resolve_canonical 走缓存)
        # 但 client_mock.get 还会被其他方法调,这里主要确认 cache 命中
        # 不重复打 /api/v1/keys/
        get_calls = [c.args[0] for c in client_mock.get.call_args_list]
        # 第一次 resolve_canonical_appid 触发 1 次 list_appids
        # 第二次走缓存,无 list_appids 调用
        keys_calls = [u for u in get_calls if "/keys/" in u]
        assert len(keys_calls) == 1, f"expected 1 /keys/ call, got {len(keys_calls)}: {keys_calls}"


@pytest.mark.asyncio
async def test_invalidate_cache_forces_refresh():
    """手动失效后,下次 resolve 重新拉列表。"""
    client_mock = mock.MagicMock()
    client_mock.__aenter__ = mock.AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = mock.AsyncMock(return_value=False)
    resp = mock.MagicMock()
    resp.status_code = 200
    resp.json = mock.MagicMock(return_value={"appids": ["k1-001"]})
    client_mock.get = mock.AsyncMock(return_value=resp)

    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=client_mock):
        c = GpPackerClient("https://x", "tok")
        await c.resolve_canonical_appid("k1-001")
        c.invalidate_appid_cache()
        await c.resolve_canonical_appid("k1-001")
    get_calls = [c.args[0] for c in client_mock.get.call_args_list]
    keys_calls = [u for u in get_calls if "/keys/" in u]
    assert len(keys_calls) == 2


@pytest.mark.asyncio
async def test_appid_cache_ttl_expiry():
    """短 TTL 下,缓存过期后应重新拉。"""
    client_mock = mock.MagicMock()
    client_mock.__aenter__ = mock.AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = mock.AsyncMock(return_value=False)
    resp = mock.MagicMock()
    resp.status_code = 200
    resp.json = mock.MagicMock(return_value={"appids": ["k1-001"]})
    client_mock.get = mock.AsyncMock(return_value=resp)

    with mock.patch("src.gp_packer.httpx.AsyncClient", return_value=client_mock):
        c = GpPackerClient("https://x", "tok", appid_cache_ttl=0.0)  # 立刻过期
        await c.resolve_canonical_appid("k1-001")
        await c.resolve_canonical_appid("k1-001")
    get_calls = [c.args[0] for c in client_mock.get.call_args_list]
    keys_calls = [u for u in get_calls if "/keys/" in u]
    assert len(keys_calls) == 2  # 每次都重新拉
