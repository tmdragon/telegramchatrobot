"""BackgroundRefresher：异步包装同步 SheetRepo/MappingRepo 调用。

SheetRepo.fetch_all / MappingRepo.load_all 是 gspread 同步阻塞 IO；
必须通过 asyncio.to_thread 投递到默认 ThreadPoolExecutor 执行，
否则 uvicorn 单线程事件循环会被阻塞。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

from src.config import AppConfig
from src.models.project import Mapping
from src.sheets.mapping_repo import MappingRepo
from src.sheets.repo import SheetRepo
from src.store.db import Store
from src.web.cache import ProjectCache


class BackgroundRefresher:
    def __init__(
        self,
        sheet_repo: SheetRepo,
        mapping_repo: MappingRepo,
        store: Store,
        cfg: AppConfig,
        cache: ProjectCache,
    ) -> None:
        self.sheet_repo = sheet_repo
        self.mapping_repo = mapping_repo
        self.store = store
        self.cfg = cfg
        self.cache = cache
        # 状态变化检测：上次 refresh 后的 project 快照
        self._previous: dict[str, Project] = {}
        self._initialized = False
        # 商店监测：每个项目的 next_check_at（用于 UI 显示 / 决定是否到时间再查）
        self.store_check_schedule: dict[str, datetime] = {}
        # Phase 3 商店监测缓存：上次检查结果（process 内）
        self.last_check_result: dict[str, dict] = {}

    def set_error_count(self, n: int) -> None:
        self._error_count = n

    def _find_project_row(self, project_id: str) -> Optional[int]:
        """查找 project_id 在第一个配置的 sheet 中的行号（1-indexed）。"""
        if not self.cfg.spreadsheets:
            return None
        ss = self.cfg.spreadsheets[0]
        return self.sheet_repo.find_row_by_project_id(
            spreadsheet_id=ss.id,
            worksheet_name=ss.name,
            project_id=project_id,
        )

    def _hydrate_status_changed_at(self, projects: list[Project]) -> None:
        """用持久化的 project_state 覆盖 Project.status_changed_at / payment_changed_at。

        SheetRepo.fetch_all 每次 rebuild dict 都把 status_changed_at 重写为
        fetched_at（"首次见到"启发式），导致跨 refresh / 跨重启都丢失原始时间。
        用 SQLite 里的 project_state 表覆盖：
        - 项目无记录（首次见到）→ 用 fetch_all 给的时间，并写库
        - 状态码未变 → 用库里记录的 status_changed_at（持久时间）
        - 状态码变了 → 用新时间，并更新库
        同逻辑应用于 payment_status / payment_changed_at。
        """
        for p in projects:
            prev = self.store.get_project_state(p.project_id)
            status_changed = False
            payment_changed = False

            # status 维度
            if p.status is not None:
                if prev is None:
                    self.store.upsert_project_state(
                        p.project_id, p.status.value, p.status_changed_at
                    )
                elif prev[0] != p.status.value:
                    self.store.upsert_project_state(
                        p.project_id, p.status.value, p.status_changed_at
                    )
                else:
                    p.status_changed_at = prev[1]
            # store_url 不变就不管（只有首次见到时持久化）

            # payment 维度（独立于 status）
            if p.payment_status is not None:
                prev_pay_code = prev[2] if prev else None
                prev_pay_at = prev[3] if prev else None
                if prev is None:
                    self.store.upsert_project_state(
                        p.project_id,
                        status_code=(prev[0] if prev else ""),
                        status_changed_at=(prev[1] if prev else p.status_changed_at or p.payment_changed_at),
                        payment_code=p.payment_status.value,
                        payment_changed_at=p.payment_changed_at,
                    )
                elif prev_pay_code != p.payment_status.value:
                    # 支付状态变了 → 更新 payment_changed_at
                    self.store.upsert_project_state(
                        p.project_id,
                        status_code=prev[0],
                        status_changed_at=prev[1] or p.status_changed_at,
                        payment_code=p.payment_status.value,
                        payment_changed_at=p.payment_changed_at,
                    )
                else:
                    p.payment_changed_at = prev_pay_at

    async def refresh_now(
        self, spreadsheet_names: Optional[list[str]] = None
    ) -> dict[str, Any]:
        """拉取 sheet + 映射，更新 cache + 持久化到 SQLite。

        Returns:
            {
              "refreshed_at": ISO8601 str,
              "project_count": int,
              "per_spreadsheet": [
                {"spreadsheet_name": str, "ok": bool, "error": str|None, "fetched_rows": int}
              ]
            }
        """
        # 决定要拉哪些 spreadsheet
        targets = [
            ss for ss in self.cfg.spreadsheets
            if spreadsheet_names is None or ss.name in spreadsheet_names
        ]

        per_ss: list[dict[str, Any]] = []
        # 提前初始化 catch-block 也会用到的变量（避免 UnboundLocalError）
        project_count = 0
        is_first_refresh = not self._initialized
        changes: list[Project] = []

        # fetch_all 是同步阻塞 —— 必须 to_thread
        try:
            projects = await asyncio.to_thread(self.sheet_repo.fetch_all, targets)
            # SheetRepo 默认 status_changed_at = fetched_at（每次 rebuild dict 都重写）。
            # 用持久化的 project_state 表覆盖，让 status_changed_at 跨重启持续。
            self._hydrate_status_changed_at(projects)
            project_count = len(projects)

            # 计算状态变化（在替换 cache 与 _previous 之前）
            new_index = {p.project_id: p for p in projects}
            if not is_first_refresh:
                for pid, new_p in new_index.items():
                    old_p = self._previous.get(pid)
                    if old_p is None:
                        # 新出现的项目 → 视为变化
                        changes.append(new_p)
                    elif old_p.status != new_p.status:
                        # 仅 status 码变化才算变化（status_changed_at 在每次
                        # SheetRepo 重建 dict 时都会被重写为 fetched_at，不能
                        # 拿来当 diff 信号）
                        changes.append(new_p)
            # 提交新快照
            self._previous = new_index
            self._initialized = True
            self.cache.replace(projects)
            # 持久化
            now = datetime.now(timezone.utc)
            for ss in targets:
                try:
                    sh = await asyncio.to_thread(self.sheet_repo.client.open_by_key, ss.id)
                    ws = await asyncio.to_thread(sh.worksheet, ss.name)
                    rows = await asyncio.to_thread(ws.get_all_values)
                    await asyncio.to_thread(
                        self.store.save_sheet_snapshot,
                        ss.id, ss.name, now, json.dumps(rows, ensure_ascii=False), None,
                    )
                    per_ss.append({
                        "spreadsheet_name": ss.name,
                        "ok": True, "error": None, "fetched_rows": len(rows),
                    })
                except Exception as e:  # noqa: BLE001
                    per_ss.append({
                        "spreadsheet_name": ss.name,
                        "ok": False, "error": f"{type(e).__name__}: {e}", "fetched_rows": 0,
                    })
        except Exception as e:  # noqa: BLE001
            # fetch_all 整体失败：所有 target 标 ok=false
            project_count = 0
            for ss in targets:
                per_ss.append({
                    "spreadsheet_name": ss.name,
                    "ok": False, "error": f"{type(e).__name__}: {e}", "fetched_rows": 0,
                })
            self.cache.set_error_count(len(targets))

        # 映射（最佳努力，失败不计入 error_count）
        try:
            mappings = await asyncio.to_thread(self.mapping_repo.load_all)
            for m in mappings:
                await asyncio.to_thread(self.store.save_mapping_snapshot, m)
        except Exception:  # noqa: BLE001
            pass

        return {
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "project_count": project_count,
            "per_spreadsheet": per_ss,
            "changes": changes,
            "is_first_refresh": is_first_refresh,
        }