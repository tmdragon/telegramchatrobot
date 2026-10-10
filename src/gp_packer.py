"""gp-packer-server API client。

提供：
- list_appids() - 拿全量 appid 列表
- get_info(appid) - 拿 /info（jks_sha256 等）
- resolve_canonical_appid(project_id) - 大小写不敏感地把 project_id 解析为
  server 上的 appid（用 5min TTL 缓存）

错误层级：
- GpPackerError 通用
- GpPackerNotFound 404
- GpPackerAuthError 401/403/410
- GpPackerRateLimited 429
"""
from __future__ import annotations

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

        返回 None 表示:project 不在 server(或 token 没 grant 覆盖)。
        区分 "项目不在" vs "网络/认证失败":通过外层捕获 GpPackerError。
        """
        m = await self._ensure_appid_cache()
        return m.get(project_id.lower())

    # ---------- 测试/调试辅助 ----------

    def invalidate_appid_cache(self) -> None:
        """强制下次 resolve_canonical_appid 重新拉。测试用。"""
        self._appid_cache = {}
        self._appid_cache_ts = 0.0
