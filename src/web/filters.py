"""Jinja2 自定义过滤器。

- status_badge: StatusCode -> 带 BEM 类名的彩色徽章 HTML 片段
- humanize_duration: 秒 -> "2 天 3 小时" / "15 分钟" / "45 秒" / "—"

颜色与显示名直接对齐 spec §3.2 表格（不在此重新枚举状态机，仅做展示映射）。
"""
from __future__ import annotations

from typing import Optional

from src.models.status import StatusCode


# spec §3.2：状态 -> (modifier, displayName)
STATUS_DISPLAY: dict[StatusCode, tuple[str, str]] = {
    StatusCode.ORDERED:              ("ordered",        "对方下单"),
    StatusCode.MAKING:               ("making",         "我方制作中"),
    StatusCode.CLIENT_REVIEW:        ("client-review",  "对方验收中"),
    StatusCode.REWORK:               ("rework",         "返工中"),
    StatusCode.WAITING_AAB:          ("waiting-aab",    "等待AAB包"),
    StatusCode.WAITING_SUBMIT:       ("waiting-submit", "等待提审"),
    StatusCode.SUBMITTING:           ("submitting",     "提审中"),
    StatusCode.FIRST_REVIEW_PASSED:  ("first-passed",   "一审通过"),
    StatusCode.FIRST_REVIEW_REJECTED:("first-rejected", "一审打回"),
    StatusCode.SECOND_REVIEW:        ("second-review",  "复审中"),
    StatusCode.REMAKING:             ("remaking",       "我方重做中"),
    StatusCode.PUBLISHED:            ("published",      "已发布"),
    StatusCode.PAID:                 ("paid",           "对方已回款"),
    StatusCode.UNPAID:               ("unpaid",         "对方未回款"),
}


def status_badge(code: StatusCode | None, raw: Optional[str] = None) -> str:
    """渲染状态徽章 HTML。code 已知则按映射渲染；否则展示 raw（用"未知"样式）。"""
    if code is not None and code in STATUS_DISPLAY:
        modifier, name = STATUS_DISPLAY[code]
        return (
            f'<span class="status-badge status-badge--{modifier}" '
            f'data-status-code="{code.value}">'
            f'<span class="status-badge__dot" aria-hidden="true"></span>'
            f'<span class="status-badge__name">{name}</span>'
            f"</span>"
        )
    text = raw if raw else "未知"
    return (
        f'<span class="status-badge status-badge--unknown" '
        f'data-status-code="">'
        f'<span class="status-badge__dot" aria-hidden="true"></span>'
        f'<span class="status-badge__name">{text}</span>'
        f"</span>"
    )


def humanize_duration(seconds: Optional[int | float]) -> str:
    """秒 -> 中文时长。负数与 None 一律显示破折号。"""
    if seconds is None or seconds < 0:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} 秒"
    if seconds < 3600:
        return f"{seconds // 60} 分钟"
    if seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h} 小时 {m} 分钟" if m else f"{h} 小时"
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    return f"{d} 天 {h} 小时" if h else f"{d} 天"