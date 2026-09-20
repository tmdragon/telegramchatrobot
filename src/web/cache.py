"""ProjectCache：内存中的项目视图缓存。

BackgroundRefresher 拉数据后调用 replace() 覆盖；UI 路由从 list_summaries() 读。
冷启动时由 overview 路由从 Store.load_latest_snapshot hydrate。

线程安全：uvicorn 单线程；BackgroundRefresher 也跑在 asyncio loop 内（同线程），
故所有访问均在单线程上，不必加锁。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from src.models.project import Project, SheetView
from src.models.status import StatusCode

if TYPE_CHECKING:
    from src.models.payment import PaymentStatus


# spec §5.3：唯一不可编辑字段 = project_id（在子表中）；status 与 project_name 可改
LOCKED_RECOGNIZED_AS: frozenset[str] = frozenset({"project_id"})


@dataclass
class ProjectSummary:
    project_id: str
    project_name: Optional[str]
    status: Optional[StatusCode]
    status_changed_at: Optional[datetime]
    dwell_seconds: int
    sheets: list[SheetView]
    editable_fields: int
    locked_field_names: list[str]
    status_raw: Optional[str] = None  # sheet 状态列原文本
    package_name: Optional[str] = None  # sheet 包名/参数 列原文
    payment_status: Optional["PaymentStatus"] = None  # 独立支付状态
    payment_raw: Optional[str] = None  # sheet 回款/支付 列原文
    # 商店监测（Phase 3 SECOND_REVIEW 自动上架检测）
    launch_region: Optional[str] = None  # sheet 原文本
    launch_region_code: Optional[str] = None  # ISO code
    store_url: Optional[str] = None
    next_store_check_at: Optional[datetime] = None
    last_store_check_at: Optional[datetime] = None
    last_store_check_result: Optional[str] = None


class ProjectCache:
    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self._last_refresh: Optional[datetime] = None
        self._error_count: int = 0

    def replace(self, projects: list[Project]) -> None:
        self._projects = {p.project_id: p for p in projects}
        self._last_refresh = datetime.now(timezone.utc)
        # 成功刷新视为无错误；错误计数由 refresher 单独写入
        self._error_count = 0

    def set_error_count(self, n: int) -> None:
        self._error_count = n

    def get(self, project_id: str) -> Optional[Project]:
        return self._projects.get(project_id)

    def list_projects(self) -> list[Project]:
        return list(self._projects.values())

    def last_refresh_at(self) -> Optional[datetime]:
        return self._last_refresh

    def error_count(self) -> int:
        return self._error_count

    def empty(self) -> bool:
        return len(self._projects) == 0

    def update_field_value(
        self,
        project_id: str,
        spreadsheet_name: str,
        sheet_name: str,
        row: int,
        col: int,
        new_value: str,
    ) -> str | None:
        """更新 cache 中对应字段值；返回被替换的原值；若字段不存在返回 None。

        注：调用方负责把 new_value 持久化（SheetRepo.update_cell + Store.record_status）。
        这里仅同步内存视图。
        """
        p = self._projects.get(project_id)
        if p is None:
            return None
        original = None
        for sv in p.sheets:
            if sv.sheet_name != sheet_name:
                continue
            for f in sv.fields:
                if f.row_index == row and f.column_index == col:
                    original = f.value
                    f.value = new_value
        return original

    def list_summaries(self, now: Optional[datetime] = None) -> list[ProjectSummary]:
        now = now or datetime.now(timezone.utc)
        out: list[ProjectSummary] = []
        for p in self._projects.values():
            editable = 0
            locked: list[str] = []
            for sv in p.sheets:
                for f in sv.fields:
                    if f.recognized_as in LOCKED_RECOGNIZED_AS:
                        locked.append(f.name)
                    else:
                        editable += 1
            dwell = 0
            if p.status_changed_at:
                dwell = max(0, int((now - p.status_changed_at).total_seconds()))
            out.append(ProjectSummary(
                project_id=p.project_id,
                project_name=p.project_name,
                status=p.status,
                status_raw=p.status_raw,
                status_changed_at=p.status_changed_at,
                dwell_seconds=dwell,
                sheets=p.sheets,
                editable_fields=editable,
                locked_field_names=locked,
                package_name=p.package_name,
                payment_status=p.payment_status,
                payment_raw=p.payment_raw,
                launch_region=p.launch_region,
                launch_region_code=p.launch_region_code,
                store_url=p.store_url,
                next_store_check_at=p.next_store_check_at,
                last_store_check_at=p.last_store_check_at,
                last_store_check_result=p.last_store_check_result,
            ))
        return out
