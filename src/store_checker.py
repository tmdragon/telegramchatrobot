"""商店上架监测：通过 HTTP GET 商店页面判断 app 是否已上架。

Google Play (和其他商店) 的上架/未上架判断：
- 已上架：HTTP 200 + 页面含 app 详情（标题、Install 按钮）
- 未上架/审核中：HTTP 200 但页面说"Item not found" / "not available"
- 解析：找 app 标题元素存在与否；或页面文本含关键词

代理池支持：通过 fetch_proxy_url(api_url, country) 获取单条代理 URL,
再传给 check_app_published 的 proxy 参数。
"""
from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import urlencode

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

# 提取 app 标题
# Google Play 真实结构：<h1><span itemprop="name">House Raise Up</span></h1>
# 宽松匹配：itemprop="name"> 后面的文本（不限于在 h1 里）
_TITLE_RE = re.compile(r'itemprop="name"[^>]*>([^<]+?)<', re.IGNORECASE)
# 兜底：<title>App Name - Apps on Google Play</title>
_PAGE_TITLE_RE = re.compile(r'<title>([^<]+?) - Apps on Google Play</title>', re.IGNORECASE)
# 辅助：找 h1 标签（即使空）
_H1_RE = re.compile(r'<h1[^>]*>', re.IGNORECASE)


async def fetch_proxy_url(api_url: str, country: Optional[str] = None, timeout: float = 10.0) -> Optional[str]:
    """从代理池 API 获取一个代理 URL。

    Args:
        api_url: 代理池 API 的 endpoint(完整 URL,带 scheme + path)
        country: 可选国家/地区代码(US/JP/IN...);作为 query 参数 country=US 传给 API
        timeout: API 请求超时

    Returns:
        代理 URL 字符串(如 "http://user:pass@ip:port");失败返回 None
    """
    if not api_url:
        return None
    params = {}
    if country:
        params["country"] = country
    full_url = f"{api_url}?{urlencode(params)}" if params else api_url
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            r = await client.get(full_url)
            r.raise_for_status()
            data = r.json()
    except Exception as e:  # noqa: BLE001
        # 静默:代理获取失败回退到 direct;调用方处理
        return None

    # 兼容多种代理 API 响应格式: {"proxy": "..."} / {"url": "..."} / 字符串本身
    if isinstance(data, str):
        return data.strip() or None
    if isinstance(data, dict):
        for key in ("proxy", "proxy_url", "url", "server"):
            v = data.get(key)
            if v:
                return str(v).strip()
    return None


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
          "reason": str,             # "published" | "not_found" | "ambiguous" | "timeout" | "error: ..."
          "url_final": str,          # 实际访问的 URL（处理 redirect 后）
        }

    注意：HTTP 状态码不可靠（Google 对 bot UA 会返回 404 而 body 仍是 app 内容）。
    必须 parse body：找到 install 按钮 / app 标题 → 上架；找到 "Item not found" → 未上架。
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

    # 提取 app 标题（不管 status 都提取，因为 Google 对 bot 可能 200 + 真内容 或 404 + 假内容）
    # 优先：<title>X - Apps on Google Play</title>
    m2 = _PAGE_TITLE_RE.search(html)
    if m2:
        title = m2.group(1).strip()
    else:
        # 兜底：itemprop="name">X<（任意位置）
        m = _TITLE_RE.search(html)
        title = m.group(1).strip() if m else None

    # 检查未上架关键词（body 里出现这些 → 明确未上架）
    for indicator in _INDICATORS_NOT_FOUND:
        if indicator in html:
            return {"published": False, "title": title, "status_code": status,
                    "reason": "not_found", "url_final": url_final}

    # 检查已上架标志（install 按钮 / 截图 / 评分 等）
    has_install = any(ind in html for ind in _INDICATORS_PUBLISHED)
    if has_install and title:
        return {"published": True, "title": title, "status_code": status,
                "reason": "published", "url_final": url_final}
    # 仅 install 标志，无标题（极少见）→ 视为上架
    if has_install:
        return {"published": True, "title": title, "status_code": status,
                "reason": "published_no_title", "url_final": url_final}
    # 仅有标题（最常见：Google 404 假页面通常不含 "Item not found"，但 <title> 仍可能匹配）
    if title:
        return {"published": True, "title": title, "status_code": status,
                "reason": "title_only", "url_final": url_final}

    # 既无 install 标志也无标题 → 兜底 pending 让下次重试
    return {"published": False, "title": title, "status_code": status,
            "reason": "ambiguous", "url_final": url_final}