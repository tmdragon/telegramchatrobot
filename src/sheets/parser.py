"""列识别与字段解析。完整定义见 spec §3.4。

设计原则：精确匹配候选列名（不模糊子串，避免误中）。
中文/英文表头都通过候选列表覆盖。
"""
from __future__ import annotations

from typing import Optional

from src.models.status import StatusCode, normalize


PROJECT_ID_CANDIDATES = ["项目编号", "编号", "ID", "Project ID", "项目 ID", "project_id"]
STATUS_CANDIDATES = ["状态", "当前状态", "项目状态", "Status", "status"]
PROJECT_NAME_CANDIDATES = ["项目名", "项目名称", "Name", "name"]
PACKAGE_NAME_CANDIDATES = ["包名", "Package", "package", "Package Name", "package_name"]


class HeaderDetector:
    """根据表头行（list[str]）匹配已知字段的列号。"""

    def __init__(self, headers: list[str]) -> None:
        # 去除表头单元格的首尾空格
        self.headers = [(h or "").strip() for h in headers]

    def find_column(self, candidates: list[str]) -> Optional[int]:
        """返回 1-indexed 列号；未找到返回 None。匹配规则：候选中任一项精确等于表头。"""
        for i, h in enumerate(self.headers, start=1):
            if h in candidates:
                return i
        return None


def parse_project_id(value: Optional[str]) -> Optional[str]:
    """项目编号解析：去首尾空格，空字符串视为 None。"""
    if value is None:
        return None
    s = value.strip()
    return s or None


def parse_status(value: Optional[str]) -> Optional[StatusCode]:
    """状态解析：委托给 status.normalize。"""
    return normalize(value)


def parse_package_name(value: Optional[str]) -> Optional[str]:
    """包名解析：去首尾空格，空字符串视为 None。"""
    if value is None:
        return None
    s = value.strip()
    return s or None