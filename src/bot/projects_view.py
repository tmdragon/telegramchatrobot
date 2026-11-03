"""项目列表渲染：/projects 的状态分组 + 等宽表格。

单独成模块（而不是塞进 bot/templates.py）：后者已 185 行，再加会破 200 行上限。

排版约定：
- 组标题在代码块**外**，普通文本（emoji + 粗体状态名 + 数量）。宽度不用对齐，
  所以 emoji 怎么渲染都不影响表格。
- 表格在等宽代码块（```）里，列宽按内容自适应，中文按 2 列算。
- 表格内只用 ASCII / 中文 / emoji，不用 ─ 这类"歧义宽度"字符——不同客户端
  宽度不一致会串列。
"""
from __future__ import annotations

import unicodedata
from typing import Optional

from src.bot.templates import (
    STATUS_DISPLAY_CN,
    STATUS_EMOJI,
    escape_markdown_v2,
    payment_display_text,
)
from src.models.status import StatusCode
from src.web.cache import ProjectSummary


# 组顺序：已发布置顶 → 其余按 StatusCode 流水线序（已下架在枚举末尾，自然收尾）
GROUP_ORDER: list[StatusCode] = [StatusCode.PUBLISHED] + [
    c for c in StatusCode if c is not StatusCode.PUBLISHED
]

HEADERS = ("项目编号", "包名", "结算")
GAP = "  "  # 列间距


def _width(text: str) -> int:
    """显示宽度：全角/中文算 2 列，组合符号不计。"""
    total = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def _render_table(rows: list[list[str]]) -> str:
    """无边框等宽表格：表头 + 分隔线 + 数据行，列宽按内容自适应。"""
    widths = [_width(h) for h in HEADERS]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _width(cell))
    rule_len = sum(widths) + len(GAP) * (len(HEADERS) - 1)

    def fmt(cells: list[str]) -> str:
        return GAP.join(_pad(c, widths[i]) for i, c in enumerate(cells)).rstrip()

    lines = [fmt(list(HEADERS)), "-" * rule_len]
    lines.extend(fmt(r) for r in rows)
    return "\n".join(lines)


def _group_summaries(
    summaries: list[ProjectSummary],
) -> list[tuple[Optional[StatusCode], Optional[str], list[ProjectSummary]]]:
    """按状态归组。

    返回 (StatusCode, 原始状态文字, 该组项目) 的列表，顺序按 GROUP_ORDER。
    状态无法识别的项目按原始状态文字再分一组（None 作为状态码）。
    """
    known: dict[StatusCode, list[ProjectSummary]] = {}
    unknown: dict[str, list[ProjectSummary]] = {}
    for s in summaries:
        if s.status is not None:
            known.setdefault(s.status, []).append(s)
        else:
            unknown.setdefault(s.status_raw or "未知", []).append(s)

    groups: list[tuple[Optional[StatusCode], Optional[str], list[ProjectSummary]]] = []
    for code in GROUP_ORDER:
        if code in known:
            groups.append((code, None, known.pop(code)))
    for raw, items in unknown.items():
        groups.append((None, raw, items))
    return groups


def _group_heading(code: Optional[StatusCode], raw: Optional[str], count: int) -> str:
    """组标题：emoji + 粗体状态名 + 数量（括号按 MarkdownV2 转义）。"""
    if code is not None:
        emoji = STATUS_EMOJI.get(code, "⚪")
        name = STATUS_DISPLAY_CN.get(code, code.value)
    else:
        emoji = "⚪"
        name = raw or "未知"
    count_text = escape_markdown_v2(f"({count})")
    return f"{emoji} *{name}* {count_text}"


def render_projects_list(summaries: list[ProjectSummary], *, title: str) -> str:
    """渲染 /projects 回复：按状态分组，每组一个等宽表格（MarkdownV2）。

    Args:
        summaries: 已按可见范围过滤好的项目摘要
        title: 顶部标题（如 "📋 *本群项目*"）
    """
    blocks = [title]
    for code, raw, items in _group_summaries(summaries):
        rows = [
            [
                s.project_id,
                s.package_name or "—",
                payment_display_text(s),
            ]
            for s in items
        ]
        blocks.append(_group_heading(code, raw, len(items)))
        blocks.append("```\n" + _render_table(rows) + "\n```")
    return "\n\n".join(blocks)
