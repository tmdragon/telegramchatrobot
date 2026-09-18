"""SheetRepo：从 Google Sheets 读取并合并为 Project 列表。完整定义见 spec §2.3 读路径。

设计：
- 每个 spreadsheet 默认读第一个 worksheet（"主表"）
- 每行用 HeaderDetector 识别 project_id / status / project_name 列
- 同一 project_id 出现在多张表 → 合并到同一个 Project.sheets
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import gspread

from src.config import SpreadsheetConfig
from src.models.project import Field, Project, SheetView
from src.sheets.parser import (
    HeaderDetector,
    PROJECT_ID_CANDIDATES,
    PROJECT_NAME_CANDIDATES,
    STATUS_CANDIDATES,
    parse_project_id,
    parse_status,
)


class SheetRepo:
    def __init__(self, client: gspread.Client) -> None:
        self.client = client

    def fetch_all(self, spreadsheets: Iterable[SpreadsheetConfig]) -> list[Project]:
        """拉取所有 spreadsheets 的数据，按 project_id 合并。"""
        projects_by_id: dict[str, Project] = {}

        for ss in spreadsheets:
            sh = self.client.open(ss.name)
            ws = sh.worksheet(ss.name)  # 默认用同名 worksheet
            rows = ws.get_all_values()
            if not rows:
                continue
            headers = rows[0]
            detector = HeaderDetector(headers)
            pid_col = detector.find_column(PROJECT_ID_CANDIDATES)
            status_col = detector.find_column(STATUS_CANDIDATES)
            name_col = detector.find_column(PROJECT_NAME_CANDIDATES)

            if pid_col is None:
                continue  # 此表无项目编号列，跳过

            fetched_at = datetime.now(timezone.utc)
            for row_idx, row in enumerate(rows[1:], start=2):
                if len(row) < len(headers):
                    row = row + [""] * (len(headers) - len(row))

                pid = parse_project_id(row[pid_col - 1] if pid_col <= len(row) else None)
                if not pid:
                    continue

                fields = []
                for col_idx, (header, value) in enumerate(zip(headers, row), start=1):
                    recognized = None
                    if col_idx == pid_col:
                        recognized = "project_id"
                    elif status_col is not None and col_idx == status_col:
                        recognized = "status"
                    elif name_col is not None and col_idx == name_col:
                        recognized = "project_name"
                    fields.append(Field(
                        name=header,
                        value=value,
                        column_index=col_idx,
                        row_index=row_idx,
                        recognized_as=recognized,
                    ))

                sheet_view = SheetView(
                    spreadsheet_id=ss.id,
                    sheet_name=ss.name,
                    fields=fields,
                    fetched_at=fetched_at,
                )

                status = parse_status(row[status_col - 1]) if status_col and status_col <= len(row) else None
                name = (row[name_col - 1].strip() or None) if name_col and name_col <= len(row) else None

                if pid not in projects_by_id:
                    projects_by_id[pid] = Project(
                        project_id=pid,
                        project_name=name,
                        status=status,
                        status_changed_at=fetched_at,  # 首次见到该状态的时间
                        sheets=[sheet_view],
                    )
                else:
                    p = projects_by_id[pid]
                    if name and not p.project_name:
                        p.project_name = name
                    if status:
                        if p.status != status:
                            # 状态变了，记录历史
                            if p.status is not None:
                                p.status_history.append((p.status, p.status_changed_at or fetched_at))
                            p.status = status
                            p.status_changed_at = fetched_at
                    p.sheets.append(sheet_view)

        return list(projects_by_id.values())
