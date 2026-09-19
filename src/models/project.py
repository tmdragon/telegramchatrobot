"""业务数据模型：Project / Field / SheetView / Mapping。完整定义见 spec §3.1。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from src.models.status import StatusCode


@dataclass
class Field:
    """sheet 中一个单元格。"""
    name: str               # 列名原文
    value: Any              # 当前值
    column_index: int       # 在原 sheet 中的列号（1-indexed，用于回写）
    row_index: int          # 在原 sheet 中的行号（1-indexed）
    recognized_as: Optional[str] = None  # 若被识别为"已知字段"，记录哪个


@dataclass
class SheetView:
    """一次拉取的一个 sheet 视图。"""
    spreadsheet_id: str
    sheet_name: str
    fields: list[Field]
    fetched_at: datetime


@dataclass
class Project:
    """业务上的一个项目，可能跨多张 sheet。"""
    project_id: str
    project_name: Optional[str] = None
    package_name: Optional[str] = None  # sheet "包名/参数" 列原文
    status: Optional[StatusCode] = None
    status_raw: Optional[str] = None  # sheet 状态列的原文本（normalize 之前的字符串）
    status_changed_at: Optional[datetime] = None
    status_history: list[tuple[StatusCode, datetime]] = field(default_factory=list)
    sheets: list[SheetView] = field(default_factory=list)


@dataclass
class Mapping:
    """项目 ↔ Telegram 群 映射。"""
    project_id: str
    chat_id: str
    note: str = ""
    enabled: bool = True
    last_broadcast_at: Optional[datetime] = None
    last_broadcast_status: Optional[str] = None
    last_error: Optional[str] = None