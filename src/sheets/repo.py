"""SheetRepo：从 Google Sheets 读取并合并为 Project 列表。完整定义见 spec §2.3 读路径。

设计：
- 用 ss.id 通过 open_by_key 打开 spreadsheet（id 是唯一标识，与文件名无关）
- 用 ss.name 在 spreadsheet 内找同名 worksheet（默认 tab）
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
    LAUNCH_REGION_CANDIDATES,
    PACKAGE_NAME_CANDIDATES,
    PAYMENT_CANDIDATES,
    PROJECT_ID_CANDIDATES,
    PROJECT_NAME_CANDIDATES,
    STATUS_CANDIDATES,
    STORE_URL_CANDIDATES,
    parse_package_name,
    parse_payment_status,
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
            sh = self.client.open_by_key(ss.id)
            ws = sh.worksheet(ss.name)  # 默认用同名 worksheet
            rows = ws.get_all_values()
            if not rows:
                continue
            headers = rows[0]
            detector = HeaderDetector(headers)
            pid_col = detector.find_column(PROJECT_ID_CANDIDATES)
            status_col = detector.find_column(STATUS_CANDIDATES)
            name_col = detector.find_column(PROJECT_NAME_CANDIDATES)
            pkg_col = detector.find_column(PACKAGE_NAME_CANDIDATES)
            pay_col = detector.find_column(PAYMENT_CANDIDATES)
            store_col = detector.find_column(STORE_URL_CANDIDATES)
            region_col = detector.find_column(LAUNCH_REGION_CANDIDATES)

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
                    elif pkg_col is not None and col_idx == pkg_col:
                        recognized = "package_name"
                    elif pay_col is not None and col_idx == pay_col:
                        recognized = "payment_status"
                    elif store_col is not None and col_idx == store_col:
                        recognized = "store_url"
                    elif region_col is not None and col_idx == region_col:
                        recognized = "launch_region"
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
                # sheet 状态列原文本（strip；空 → None）
                raw_cell = row[status_col - 1] if status_col and status_col <= len(row) else None
                status_raw = raw_cell.strip() if raw_cell else None
                status_raw = status_raw or None
                name = (row[name_col - 1].strip() or None) if name_col and name_col <= len(row) else None
                pkg_name = parse_package_name(row[pkg_col - 1]) if pkg_col and pkg_col <= len(row) else None
                # 支付状态（独立列；找不到时为 None）
                pay_raw = row[pay_col - 1].strip() if pay_col and pay_col <= len(row) else None
                pay_raw = pay_raw or None
                payment = parse_payment_status(pay_raw)
                # 商店地址（GP/App Store URL）
                store_url = row[store_col - 1].strip() if store_col and store_col <= len(row) else None
                store_url = store_url or None
                # 上架地区
                launch_region = row[region_col - 1].strip() if region_col and region_col <= len(row) else None
                launch_region = launch_region or None

                if pid not in projects_by_id:
                    projects_by_id[pid] = Project(
                        project_id=pid,
                        project_name=name,
                        package_name=pkg_name,
                        store_url=store_url,
                        launch_region=launch_region,
                        status=status,
                        status_raw=status_raw,
                        status_changed_at=fetched_at,  # 首次见到该状态的时间
                        payment_status=payment,
                        payment_raw=pay_raw,
                        payment_changed_at=fetched_at if payment else None,
                        sheets=[sheet_view],
                    )
                else:
                    p = projects_by_id[pid]
                    if name and not p.project_name:
                        p.project_name = name
                    if pkg_name and not p.package_name:
                        p.package_name = pkg_name
                    if store_url and not p.store_url:
                        p.store_url = store_url
                    if launch_region and not p.launch_region:
                        from src.country import normalize_country
                        p.launch_region = launch_region
                        p.launch_region_code = normalize_country(launch_region)
                    # 支付状态首次见到时写入；后续 sheet 可更新
                    if payment is not None:
                        if p.payment_status != payment:
                            if p.payment_status is not None:
                                p.payment_changed_at = fetched_at
                            p.payment_status = payment
                    if pay_raw and pay_raw != p.payment_raw:
                        p.payment_raw = pay_raw
                    if status:
                        if p.status != status:
                            # 状态变了，记录历史
                            if p.status is not None:
                                p.status_history.append((p.status, p.status_changed_at or fetched_at))
                            p.status = status
                            p.status_changed_at = fetched_at
                    # 状态没变也允许更新 status_raw（多 sheet 可能写不同原文本）
                    if status_raw and (p.status_raw != status_raw):
                        p.status_raw = status_raw
                    p.sheets.append(sheet_view)

        return list(projects_by_id.values())

    def update_cell(
        self,
        spreadsheet_name: str,
        worksheet_name: str,
        row: int,
        col: int,
        new_value: str,
    ) -> str:
        """写入单元格，重读校验，返回最终值。

        Raises:
            WriteVerificationError: 写后读出的值与 new_value 不一致。
        """
        sh = self.client.open(spreadsheet_name)
        ws = sh.worksheet(worksheet_name)
        ws.update_cell(row, col, new_value)
        verified = ws.cell(row, col).value
        if verified != new_value:
            raise WriteVerificationError(
                f"Write verification failed at {spreadsheet_name}!{worksheet_name} "
                f"({row},{col}): wrote {new_value!r}, read {verified!r}"
            )
        return verified

    def find_row_by_project_id(
        self,
        spreadsheet_id: str,
        worksheet_name: str,
        project_id: str,
    ) -> Optional[int]:
        """根据 project_id 列查找项目所在行号（1-indexed）。找不到返回 None。

        Phase 3 商店监测：检测到上架后用这个定位要 update_cell 的行。
        """
        sh = self.client.open_by_key(spreadsheet_id)
        ws = sh.worksheet(worksheet_name)
        rows = ws.get_all_values()
        for idx, row in enumerate(rows[1:], start=2):
            if row and row[0] == project_id:
                return idx
        return None

    def find_column_by_header(
        self,
        spreadsheet_id: str,
        worksheet_name: str,
        header_name: str,
    ) -> Optional[int]:
        """根据 header_name 找列号（1-indexed）。"""
        sh = self.client.open_by_key(spreadsheet_id)
        ws = sh.worksheet(worksheet_name)
        headers = ws.row_values(1)
        for idx, h in enumerate(headers, start=1):
            if h.strip() == header_name.strip():
                return idx
        return None

    def update_cell_by_header(
        self,
        spreadsheet_id: str,
        worksheet_name: str,
        row: int,
        header_name: str,
        new_value: str,
    ) -> str:
        """按 header 名定位列 + 行号，写入并校验。"""
        col = self.find_column_by_header(spreadsheet_id, worksheet_name, header_name)
        if col is None:
            raise ValueError(f"Header {header_name!r} not found in {worksheet_name}")
        # 调用底层的 update_cell（用 spreadsheet_id 重新打开）
        sh = self.client.open_by_key(spreadsheet_id)
        ws = sh.worksheet(worksheet_name)
        ws.update_cell(row, col, new_value)
        verified = ws.cell(row, col).value
        if verified != new_value:
            raise WriteVerificationError(
                f"Write verification failed at {worksheet_name} "
                f"({row},{header_name}={col}): wrote {new_value!r}, read {verified!r}"
            )
        return verified


class WriteVerificationError(RuntimeError):
    """写后重读校验失败。"""
