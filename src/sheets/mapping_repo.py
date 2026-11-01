"""MappingRepo：项目 ↔ 群 映射表的 CRUD。完整定义见 spec §4。

映射表 schema：
| 项目编号 | 群 chat_id | 备注 | 是否启用 | 上次播报时间 |
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import gspread

from src.models.project import Mapping

log = logging.getLogger(__name__)

HEADERS = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]


def _truthy(s: str) -> bool:
    return s.strip().upper() in ("TRUE", "YES", "1", "是", "✓", "✅")


@dataclass
class GroupView:
    """按 chat_id 聚合的一组 mapping 视图(给 /groups 管理页用)。"""
    chat_id: str
    note: str = ""
    projects: list[str] = field(default_factory=list)
    enabled_state: str = "all"  # 'all' | 'partial' | 'none'
    last_broadcast_at: str | None = None


class MappingRepo:
    def __init__(self, client: gspread.Client, spreadsheet_name: str = "项目群映射") -> None:
        self.client = client
        self.spreadsheet_name = spreadsheet_name

    def _ws(self):
        sh = self.client.open(self.spreadsheet_name)
        return sh.worksheet(self.spreadsheet_name)

    def load_all(self) -> list[Mapping]:
        ws = self._ws()
        rows = ws.get_all_values()
        if len(rows) < 2:
            return []
        mappings = []
        for row in rows[1:]:
            if len(row) < 5:
                row = row + [""] * (5 - len(row))
            pid = row[0].strip()
            cid = row[1].strip()
            # 必须有 chat_id;project_id 可为空(纯群映射,无关联项目)
            if not cid:
                continue
            mappings.append(Mapping(
                project_id=pid,
                chat_id=cid,
                note=row[2].strip(),
                enabled=_truthy(row[3]),
                last_broadcast_at=row[4].strip() or None,
            ))
        return mappings

    def _find_row(self, ws, project_id: str) -> int | None:
        cell = ws.find(project_id)
        return cell.row if cell is not None else None

    def upsert(self, mapping: Mapping) -> None:
        ws = self._ws()
        row_idx = self._find_row(ws, mapping.project_id)
        row_data = [
            mapping.project_id,
            mapping.chat_id,
            mapping.note,
            "TRUE" if mapping.enabled else "FALSE",
            mapping.last_broadcast_at.isoformat() if mapping.last_broadcast_at else "",
        ]
        if row_idx is None:
            ws.append_row(row_data)
        else:
            for col_idx, value in enumerate(row_data, start=1):
                ws.update_cell(row_idx, col_idx, value)

    def delete(self, project_id: str) -> None:
        """软删除：enabled=false。"""
        ws = self._ws()
        row_idx = self._find_row(ws, project_id)
        if row_idx is None:
            return
        ws.update_cell(row_idx, 4, "FALSE")

    # === 群视角的 CRUD(/groups 管理页用) ===

    def load_all_grouped(self) -> list[GroupView]:
        """按 chat_id 聚合现有 mappings,返回每组的 GroupView。

        - projects: 该 chat_id 下的所有 project_id(按 sheet 顺序)
        - note: 第一个非空备注
        - enabled_state: 'all' / 'partial' / 'none' 取决于组内 enabled 状态分布
        """
        mappings = self.load_all()
        by_chat: dict[str, list[Mapping]] = {}
        for m in mappings:
            by_chat.setdefault(m.chat_id, []).append(m)
        out: list[GroupView] = []
        for chat_id, ms in by_chat.items():
            enabled_count = sum(1 for m in ms if m.enabled)
            if enabled_count == len(ms):
                state = "all"
            elif enabled_count == 0:
                state = "none"
            else:
                state = "partial"
            note = next((m.note for m in ms if m.note), "")
            last_broadcast = next(
                (m.last_broadcast_at for m in ms if m.last_broadcast_at),
                None,
            )
            out.append(GroupView(
                chat_id=chat_id,
                note=note,
                # 过滤空 project_id(纯群映射的行不进 projects 列表)
                projects=[m.project_id for m in ms if m.project_id],
                enabled_state=state,
                last_broadcast_at=last_broadcast,
            ))
        # 按 chat_id 排序(稳定)
        out.sort(key=lambda g: g.chat_id)
        return out

    def _find_rows_by_chat_id(self, ws, chat_id: str) -> list[int]:
        """返回所有 chat_id 等于给定值的工作表行号(1-indexed,不含表头)。"""
        rows = ws.get_all_values()
        out: list[int] = []
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) >= 2 and row[1].strip() == chat_id:
                out.append(idx)
        return out

    def chat_id_exists(self, chat_id: str) -> bool:
        ws = self._ws()
        return bool(self._find_rows_by_chat_id(ws, chat_id))

    def create_group(self, chat_id: str, project_id: str, note: str = "", enabled: bool = True) -> None:
        """创建群(写入该 chat_id 的第一个 mapping)。

        若 chat_id 已存在则抛 ValueError;冲突应该在前端表单层校验,
        这里做最后一道防线。
        """
        if self.chat_id_exists(chat_id):
            raise ValueError(f"chat_id {chat_id!r} already exists")
        self._append_mapping(chat_id, project_id, note, enabled)

    def _append_mapping(self, chat_id: str, project_id: str, note: str, enabled: bool) -> None:
        """底层:无守卫地 append 一行 mapping(给 set_group_projects 复用)。"""
        ws = self._ws()
        row_data = [
            project_id,
            chat_id,
            note,
            "TRUE" if enabled else "FALSE",
            "",
        ]
        ws.append_row(row_data, value_input_option="USER_ENTERED")

    def update_group(self, chat_id: str, note: str, enabled: bool) -> None:
        """更新该 chat_id 下所有 mapping 的 note 和 enabled。"""
        ws = self._ws()
        rows = self._find_rows_by_chat_id(ws, chat_id)
        for row_idx in rows:
            ws.update_cell(row_idx, 3, note)  # 备注列
            ws.update_cell(row_idx, 4, "TRUE" if enabled else "FALSE")  # 启用列

    def disable_group(self, chat_id: str) -> None:
        """软删除:把该 chat_id 下所有 mapping 的 enabled 设为 FALSE。"""
        ws = self._ws()
        rows = self._find_rows_by_chat_id(ws, chat_id)
        for row_idx in rows:
            ws.update_cell(row_idx, 4, "FALSE")

    @staticmethod
    def _norm(s: str) -> str:
        """归一化用于比较:去首尾空格 + 忽略大小写。"""
        return (s or "").strip().casefold()

    def _group_rows(
        self, rows: list[list[str]], chat_id: str
    ) -> list[tuple[int, str, str, bool]]:
        """挑出某个群在表里的行:(行号, 项目编号, 备注, 是否启用)。

        项目编号为空 = 「纯群映射」行(群本身存在,但没关联项目)。
        行号是 1-indexed 的表内行号(第 1 行是表头)。
        """
        want_chat = self._norm(chat_id)
        out: list[tuple[int, str, str, bool]] = []
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) < 2 or self._norm(row[1]) != want_chat:
                continue
            pid = row[0].strip() if len(row) > 0 else ""
            note = row[2].strip() if len(row) > 2 else ""
            enabled = _truthy(row[3]) if len(row) > 3 else False
            out.append((idx, pid, note, enabled))
        return out

    def set_group_projects(self, chat_id: str, project_ids: list[str]) -> None:
        """把该 chat_id 下的映射行同步成给定 project_ids 集合。

        - 项目号不在 desired 里的行:**直接删行**(不是把 enabled 改 FALSE)
        - desired 里没有对应行的:追加新行(备注/启用状态跟群现有行一致)
        - 已有行的 enabled **不动** —— 群级「启用/停用」由 update_group 统一管;
          否则「取消勾选启用再保存」会被这里重新启用,群永远停用不掉

        行号按 ws.get_all_values() 的 1-indexed 表内行号算,删行会让下面的行
        往上顶,所以删多行时必须倒序删。
        """
        desired = [p.strip() for p in project_ids if p and p.strip()]
        desired_norm = {self._norm(p) for p in desired}
        ws = self._ws()

        # 1) 删掉不在 desired 里的项目行 —— 倒序,否则行号会错位
        rows = ws.get_all_values()
        stale = [
            idx for idx, pid, _note, _en in self._group_rows(rows, chat_id)
            if pid and self._norm(pid) not in desired_norm
        ]
        for idx in sorted(stale, reverse=True):
            ws.delete_rows(idx)
        if stale:
            log.info(
                "groups: 删除 chat_id=%s 的映射行 %s", chat_id, stale
            )

        # 2) 补齐 desired 里缺的行
        rows = ws.get_all_values()
        group_rows = self._group_rows(rows, chat_id)
        have = {self._norm(pid) for _idx, pid, _note, _en in group_rows if pid}
        group_note = next((n for _i, _p, n, _e in group_rows if n), "")
        group_enabled = any(en for _i, _p, _n, en in group_rows) if group_rows else True
        for pid in desired:
            if self._norm(pid) in have:
                continue
            self._append_mapping(
                chat_id, project_id=pid, note=group_note, enabled=group_enabled
            )
