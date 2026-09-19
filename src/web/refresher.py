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
        # fetch_all 是同步阻塞 —— 必须 to_thread
        try:
            projects = await asyncio.to_thread(self.sheet_repo.fetch_all, targets)
            project_count = len(projects)

            # 计算状态变化（在替换 cache 与 _previous 之前）
            is_first_refresh = not self._initialized
            changes: list[Project] = []
            new_index = {p.project_id: p for p in projects}
            if not is_first_refresh:
                for pid, new_p in new_index.items():
                    old_p = self._previous.get(pid)
                    if old_p is None:
                        # 新出现的项目 → 视为变化
                        changes.append(new_p)
                    elif (old_p.status != new_p.status
                          or old_p.status_changed_at != new_p.status_changed_at):
                        # 状态码或 status_changed_at 变化 → 视为变化
                        changes.append(new_p)
            # 提交新快照
            self._previous = new_index
            self._initialized = True
            self.cache.replace(projects)
            # 持久化
            now = datetime.now(timezone.utc)
            for ss in targets:
                try:
                    sh = await asyncio.to_thread(self.sheet_repo.client.open, ss.name)
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