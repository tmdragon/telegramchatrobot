"""商店上架监测：通过 HTTP GET 商店页面判断 app 是否已上架。

Google Play (和其他商店) 的上架/未上架判断：
- 已上架：HTTP 200 + 页面含 app 详情（标题、Install 按钮）
- 未上架/审核中：HTTP 200 但页面说"Item not found" / "not available"
- 解析：找 app 标题元素存在与否；或页面文本含关键词

Phase 1：直接 HTTP（无代理）。Phase 2 可加 proxy 轮换。
"""
from __future__ import annotations

import re
from typing import Optional

import httpx


# Google Play 页面上 app 已上架的标志
_INDICATORS_PUBLISHED = [
    'aria-label="Install',  # Install button
    "Install&nbsp;",  # legacy
    'data-g-id="install"',  # alt
    "Developer",  # has developer section
]

# 未上架 / 找不到的标志
_INDICATORS_NOT_FOUND = [
    "Item not found",
    "We're sorry, the requested resource could not be found",
    "This app is not available",
    "Not found for your request",
    "我们找不到您要找的物品",  # 中文 fallback（Google Play 简中）
    "此应用在您所在的国家/地区不可用",
]

# 提取 app 标题（<h1 itemprop="name"> ... </h1> 或 <title>...</title>）
_TITLE_RE = re.compile(r'<h1[^>]*itemprop="name"[^>]*>([^<]+)</h1>', re.IGNORECASE)
_PAGE_TITLE_RE = re.compile(r'<title>([^<]+?) - Apps on Google Play</title>', re.IGNORECASE)


async def check_app_published(
    url: str,
    proxy: Optional[str] = None,
    timeout: float = 15.0,
) -> dict:
    """HTTP GET 商店页面，判断 app 是否已上架。

    Args:
        url: 商店页面 URL（如 https://play.google.com/store/apps/details?id=com.xxx）
        proxy: 可选代理（如 http://host:port）
        timeout: 请求超时秒数

    Returns:
        {
          "published": bool,
          "title": str | None,       # 提取的 app 标题
          "status_code": int,
          "reason": str,             # "published" | "not_found" | "error: ..."
          "url_final": str,          # 实际访问的 URL（处理 redirect 后）
        }
    """
    if not url:
        return {"published": False, "title": None, "status_code": 0,
                "reason": "no_url", "url_final": ""}

    proxies = proxy if proxy else None
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    }

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            proxies=proxies,
            headers=headers,
        ) as client:
            r = await client.get(url)
            html = r.text
            status = r.status_code
            url_final = str(r.url)
    except httpx.TimeoutException:
        return {"published": False, "title": None, "status_code": 0,
                "reason": "timeout", "url_final": url}
    except Exception as e:  # noqa: BLE001
        return {"published": False, "title": None, "status_code": 0,
                "reason": f"error: {type(e).__name__}: {e}", "url_final": url}

    # HTTP 4xx/5xx：未上架或服务异常
    if status >= 400:
        return {"published": False, "title": None, "status_code": status,
                "reason": f"http_{status}", "url_final": url_final}

    # 检查未上架关键词
    for indicator in _INDICATORS_NOT_FOUND:
        if indicator in html:
            return {"published": False, "title": None, "status_code": status,
                    "reason": "not_found", "url_final": url_final}

    # 提取 app 标题
    m = _TITLE_RE.search(html)
    title = m.group(1).strip() if m else None
    if title is None:
        m2 = _PAGE_TITLE_RE.search(html)
        if m2:
            title = m2.group(1).strip()

    # 检查已上架标志
    has_install = any(ind in html for ind in _INDICATORS_PUBLISHED)
    if has_install or title:
        return {"published": True, "title": title, "status_code": status,
                "reason": "published", "url_final": url_final}

    # 兜底：HTTP 200 但未识别 → 标记为 pending 让下次重试
    return {"published": False, "title": title, "status_code": status,
            "reason": "ambiguous", "url_final": url_final}