"""gp-packer-server API client。

提供：
- list_appids() - 拿全量 appid 列表
- get_info(appid) - 拿 /info（jks_sha256 等）
- resolve_canonical_appid(project_id) - 大小写不敏感地把 project_id 解析为
  server 上的 appid（用 5min TTL 缓存）；三级匹配：完整名 → 括号前基础名 → 前缀
- strip_paren_suffix(project_id) - 截掉括号后缀,取基础名（TTR-0680(6514b) → TTR-0680）
- appid_candidates(project_id) - 按尝试顺序列出查找键（用于错误文案）
- parse_properties(text) - 解析 Java .properties 文本为 dict（用于读 hashKey 等字段）

错误层级：
- GpPackerError 通用
- GpPackerNotFound 404
- GpPackerAuthError 401/403/410
- GpPackerRateLimited 429
"""
from __future__ import annotations

import configparser
import time
from typing import Optional

import httpx


class GpPackerError(Exception):
    """Base error."""

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        detail: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


class GpPackerNotFound(GpPackerError):
    """404 - appid 不在 server 上。"""


class GpPackerAuthError(GpPackerError):
    """401/403/410 - token 问题（invalid / forbidden / expired / revoked）。"""


class GpPackerRateLimited(GpPackerError):
    """429 - rate limit hit。"""


class GpPackerClient:
    """gp-packer-server async HTTP client.

    配置来自 AppConfig.gp_packer_token / gp_packer_base_url。
    token 为空时构造抛 ValueError;调用方应在路由层判断
    `app.state.gp_packer_client is None` 返回 503 而非构造空 client。
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 15.0,
        appid_cache_ttl: float = 300.0,
    ) -> None:
        if not token:
            raise ValueError("GpPackerClient: token is required")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._appid_cache: dict[str, str] = {}  # lowercase -> canonical
        self._appid_cache_ts: float = 0.0
        self._appid_cache_ttl = appid_cache_ttl

    # ---------- HTTP ----------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    @staticmethod
    def _extract_detail(r: httpx.Response) -> Optional[str]:
        try:
            data = r.json()
        except Exception:
            return None
        if isinstance(data, dict):
            return data.get("detail")
        return None

    async def _get_json(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(url, headers=self._headers())
        except httpx.RequestError as e:
            raise GpPackerError(f"request failed: {type(e).__name__}: {e}") from e

        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            raise GpPackerNotFound("appid not found", status=404)
        if r.status_code in (401, 403):
            detail = self._extract_detail(r)
            raise GpPackerAuthError(
                detail or "auth failed",
                status=r.status_code,
                detail=detail,
            )
        if r.status_code == 410:
            raise GpPackerAuthError(
                "token expired",
                status=410,
                detail=self._extract_detail(r),
            )
        if r.status_code == 429:
            raise GpPackerRateLimited("rate limit exceeded", status=429)
        # 4xx/5xx fallback
        raise GpPackerError(
            f"HTTP {r.status_code}",
            status=r.status_code,
            detail=self._extract_detail(r),
        )

    # ---------- Public API ----------

    async def list_appids(self) -> list[str]:
        """全量可见 appid 列表。"""
        data = await self._get_json("/api/v1/keys/")
        return list(data.get("appids", []))

    async def get_info(self, appid: str) -> dict:
        """/info 响应原始 dict（jks_sha256 / jks_size / main_activity / properties）。"""
        return await self._get_json(f"/api/v1/keys/{appid}/info")

    # ---------- 大小写不敏感 ----------

    async def _ensure_appid_cache(self) -> dict[str, str]:
        """返回 {lowercase: canonical} map,5 分钟 TTL。"""
        now = time.monotonic()
        if self._appid_cache and (now - self._appid_cache_ts) < self._appid_cache_ttl:
            return self._appid_cache
        appids = await self.list_appids()
        self._appid_cache = {a.lower(): a for a in appids}
        self._appid_cache_ts = now
        return self._appid_cache

    async def resolve_canonical_appid(self, project_id: str) -> Optional[str]:
        """大小写不敏感地把 project_id 解析为 server 上的 appid。

        三级匹配:
        1. 完整 project_id 精确匹配(项目名与 server 完全一致时走这条)
        2. 括号前基础名精确匹配(TTR-0680(6514b) → TTR-0680)
        3. 基础名前缀匹配(TTR-0680( → TTR-0680(6541B))

        第 2/3 级是因为 sheet 里的项目名与 server 上的 appid 括号后缀可能不同
        (例:sheet 是 TTR-0680(6514b),server 是 TTR-0680(6541B))。

        返回 None 表示:project 不在 server(或 token 没 grant 覆盖)。
        区分 "项目不在" vs "网络/认证失败":通过外层捕获 GpPackerError。
        """
        m = await self._ensure_appid_cache()
        # 1/2 级:完整名 + 括号前基础名,精确匹配
        for key in appid_candidates(project_id):
            hit = m.get(key.lower())
            if hit is not None:
                return hit
        base = strip_paren_suffix(project_id)
        if base == project_id:
            return None
        # 3 级:前缀匹配 base + "(" / base + "（"
        prefixes = (base.lower() + "(", base.lower() + "（")
        matches = [
            a for a in m.values()
            if a.lower().startswith(prefixes[0]) or a.lower().startswith(prefixes[1])
        ]
        if not matches:
            return None
        # 多个候选时优先选括号后缀与项目名一致的那个(项目名理论上唯一,这是兜底)
        want = _paren_suffix(project_id)
        for a in matches:
            if _paren_suffix(a) == want:
                return a
        return matches[0]

    # ---------- 测试/调试辅助 ----------

    def invalidate_appid_cache(self) -> None:
        """强制下次 resolve_canonical_appid 重新拉。测试用。"""
        self._appid_cache = {}
        self._appid_cache_ts = 0.0


# ---------- 项目名 → 查找键 ----------

# 左括号:半角 + 全角
_PAREN_OPENERS = ("(", "（")


def strip_paren_suffix(project_id: str) -> str:
    """截掉第一个左括号及其之后的内容,返回基础名。

    sheet 里的项目名可能带构建后缀(如 TTR-0680(6514b)),而 server 上的 appid
    后缀可能不同(如 TTR-0680(6541B))或干脆没有括号 —— 基础名才是稳定的查找键。

    没有左括号、或左括号前没有可用内容时,原样返回。
    """
    positions = [i for i in (project_id.find(c) for c in _PAREN_OPENERS) if i != -1]
    if not positions:
        return project_id
    base = project_id[:min(positions)].strip()
    return base or project_id


def appid_candidates(project_id: str) -> list[str]:
    """按尝试顺序返回查找键:完整 project_id → 括号前基础名。

    用于错误文案(告诉用户试过哪些 key)。
    """
    candidates = [project_id]
    base = strip_paren_suffix(project_id)
    if base != project_id:
        candidates.append(base)
    return candidates


def _paren_suffix(text: str) -> str:
    """取第一对括号内的内容(小写)。没有括号返回 ""。"""
    positions = [(text.find(c), c) for c in _PAREN_OPENERS]
    positions = [(i, c) for i, c in positions if i != -1]
    if not positions:
        return ""
    start, opener = min(positions)
    closer = ")" if opener == "(" else "）"
    end = text.find(closer, start + 1)
    if end == -1:
        end = len(text)
    return text[start + 1:end].strip().lower()


def parse_properties(text: str) -> dict[str, str]:
    """解析 Java .properties 文本为 dict。空文本返回 {}。

    gp-packer /info 返回的 properties 字段是 verbatim 文件内容,UTF-8,
    \\n 分隔多行,格式是 `key=value`(无 [section] header)。

    configparser 需要 [section] header 且默认把 key 转小写(optionxform),
    这里手动改 optionxform 保留原始大小写(.properties 文件的 key 是大小写敏感的)。
    """
    if not text:
        return {}
    parser = configparser.ConfigParser()
    # 保留原始 key 大小写(默认会 lowercase → "hashKey" 变 "hashkey" 取不到)
    parser.optionxform = str
    try:
        parser.read_string("[default]\n" + text)
    except configparser.Error:
        return {}
    return {k: v for k, v in parser["default"].items()}
