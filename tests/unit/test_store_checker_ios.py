"""iOS 上架检测(iTunes Search API)测试。

包含:
- _check_ios_app 单元测试(原 Task 3)
- check_app_published platform 派发测试(Task 4)
"""
from __future__ import annotations

import unittest.mock as mock

import pytest

from src.store_checker_ios import _check_ios_app
from src.store_checker import check_app_published


pytestmark = pytest.mark.asyncio


def _fake_client(json_data, status_code=200, text=""):
    """构造 httpx.AsyncClient 的 mock。"""

    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self._json = json_data
            self.text = text

        def json(self):
            return self._json

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _Resp()

    return _Client()


async def test_ios_published_when_result_count_one():
    payload = {"resultCount": 1, "results": [{"trackName": "My Cool Game", "trackId": 12345}]}
    with mock.patch("src.store_checker_ios.httpx.AsyncClient", return_value=_fake_client(payload)):
        result = await _check_ios_app("https://apps.apple.com/app/id12345", proxy=None, timeout=10)
    assert result["published"] is True
    assert result["title"] == "My Cool Game"
    assert result["reason"] == "published"


async def test_ios_not_published_when_result_count_zero():
    payload = {"resultCount": 0, "results": []}
    with mock.patch("src.store_checker_ios.httpx.AsyncClient", return_value=_fake_client(payload)):
        result = await _check_ios_app("https://apps.apple.com/app/id12345", proxy=None, timeout=10)
    assert result["published"] is False
    assert result["reason"] == "not_found"


async def test_ios_error_when_http_500():
    with mock.patch("src.store_checker_ios.httpx.AsyncClient",
                     return_value=_fake_client({}, status_code=500)):
        result = await _check_ios_app("https://apps.apple.com/app/id12345", proxy=None, timeout=10)
    assert result["published"] is False
    assert result["reason"].startswith("error")
    assert "500" in result["reason"]


async def test_ios_error_when_url_has_no_id():
    result = await _check_ios_app("https://play.google.com/store/apps/details?id=com.x",
                                  proxy=None, timeout=10)
    assert result["published"] is False
    assert "App Store ID" in result["reason"]
    assert result["reason"].startswith("error")


async def test_ios_error_when_json_malformed():
    with mock.patch("src.store_checker_ios.httpx.AsyncClient", return_value=_fake_client(None)):
        # json() raises ValueError
        result = await _check_ios_app("https://apps.apple.com/app/id12345", proxy=None, timeout=10)
    assert result["published"] is False
    assert result["reason"].startswith("error")


async def test_ios_passes_proxy_to_httpx():
    payload = {"resultCount": 1, "results": [{"trackName": "X", "trackId": 1}]}
    captured: dict = {}

    class _Client:
        def __init__(self, *a, **kw):
            captured.update(kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            class _R:
                status_code = 200

                def json(self_inner):
                    return payload

            return _R()

    with mock.patch("src.store_checker_ios.httpx.AsyncClient", side_effect=_Client):
        await _check_ios_app("https://apps.apple.com/app/id1",
                             proxy="http://proxy:8080", timeout=10)
    assert captured.get("proxies") == "http://proxy:8080"


# ---- check_app_published dispatch tests (Task 4) ----


async def test_dispatch_to_ios_when_platform_ios():
    """platform='ios' 时 check_app_published 应派发到 _check_ios_app(iTunes API)。"""
    payload = {"resultCount": 1, "results": [{"trackName": "iOS App", "trackId": 999}]}
    with mock.patch("src.store_checker_ios.httpx.AsyncClient", return_value=_fake_client(payload)):
        result = await check_app_published(
            "https://apps.apple.com/app/id999", platform="ios", proxy=None, timeout=10
        )
    assert result["published"] is True
    assert result["title"] == "iOS App"


async def test_default_platform_is_gp():
    """不传 platform 时默认 gp 走原 HTML 路径;传不可达 URL 应触发网络错误而非 iOS 路径。

    此测试不 mock httpx,而是传 .invalid TLD + 短超时,期望 GP 路径因 ConnectError 返回 error。
    """
    result = await check_app_published(
        "http://this-domain-definitely-does-not-exist-abc123.invalid/foo",
        timeout=2,
    )
    assert result["published"] is False
    assert result["reason"].startswith("error") or result["reason"] in ("timeout", "ambiguous")
