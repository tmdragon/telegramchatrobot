"""iOS 上架检测：通过 iTunes Search API 查询 App Store ID 的发布状态。

对应 Google Play HTML 路径(store_checker.check_app_published)，由其在
platform="ios" 时派发至此模块。

iTunes Search API:
- 输入:数字 App Store ID(可从 apps.apple.com/app/idN URL 提取)
- 输出:JSON 含 resultCount + results 数组;resultCount=1 已上架,=0 未上架。
"""
from __future__ import annotations

import re
from typing import Optional

import httpx


# iOS App Store URL → App Store ID 提取
# 兼容 apps.apple.com/app/idN 与 apps.apple.com/cn/app/{slug}/idN
# 容忍末尾 query / fragment
_APP_STORE_ID_RE = re.compile(r"/id(\d+)(?:$|[/?#])")


def extract_app_store_id(url: str) -> Optional[int]:
    """从 iOS App Store URL 提取数字 App Store ID。无法提取时返回 None。"""
    if not url:
        return None
    m = _APP_STORE_ID_RE.search(url)
    if not m:
        return None
    return int(m.group(1))


async def _check_ios_app(
    url: str,
    *,
    proxy: Optional[str] = None,
    timeout: float = 15.0,
) -> dict:
    """iOS 上架检测:通过 iTunes Search API 查询 App Store ID 的发布状态。

    返回 schema 与 check_app_published 一致:
      {published: bool, title: str | None, status_code: int, reason: str, url_final: str}

    reason 取值:
      - "published":iTunes 返回 resultCount=1
      - "not_found":iTunes 返回 resultCount=0
      - "no_url":URL 为空
      - "error: <details>":HTTP / JSON / URL 异常
    """
    if not url:
        return {"published": False, "title": None, "status_code": 0,
                "reason": "no_url", "url_final": ""}

    app_id = extract_app_store_id(url)
    if app_id is None:
        return {"published": False, "title": None, "status_code": 0,
                "reason": f"error: URL 中未找到 App Store ID: {url}", "url_final": url}

    api_url = f"https://itunes.apple.com/lookup?id={app_id}"
    proxies = proxy if proxy else None
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            proxies=proxies,
            headers=headers,
        ) as client:
            r = await client.get(api_url)
            status = r.status_code
            data = r.json()
        if not isinstance(data, dict):
            return {"published": False, "title": None, "status_code": status,
                    "reason": "error: iTunes API 返回非 JSON", "url_final": url}
    except httpx.TimeoutException:
        return {"published": False, "title": None, "status_code": 0,
                "reason": "timeout", "url_final": url}
    except ValueError:
        return {"published": False, "title": None, "status_code": 0,
                "reason": "error: iTunes API 返回非 JSON", "url_final": url}
    except Exception as e:  # noqa: BLE001
        return {"published": False, "title": None, "status_code": 0,
                "reason": f"error: {type(e).__name__}: {e}", "url_final": url}

    if status != 200:
        return {"published": False, "title": None, "status_code": status,
                "reason": f"error: iTunes API HTTP {status}", "url_final": url}

    count = data.get("resultCount", 0)
    if count == 0 or not data.get("results"):
        return {"published": False, "title": None, "status_code": status,
                "reason": "not_found", "url_final": url}

    track_name = data["results"][0].get("trackName")
    return {"published": True, "title": track_name, "status_code": status,
            "reason": "published", "url_final": url}
