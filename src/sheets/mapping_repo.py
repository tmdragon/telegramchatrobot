"""MappingRepo：项目 ↔ 群 映射表的 CRUD。完整定义见 spec §4。

映射表 schema：
| 项目编号 | 群 chat_id | 备注 | 是否启用 | 上次播报时间 |
"""
from __future__ import annotations

import gspread

from src.models.project import Mapping


HEADERS = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]


def _truthy(s: str) -> bool:
    return s.strip().upper() in ("TRUE", "YES", "1", "是", "✓", "✅")


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
            if not pid:
                continue
            mappings.append(Mapping(
                project_id=pid,
                chat_id=row[1].strip(),
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
