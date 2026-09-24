"""Jinja2 自定义过滤器。

- status_badge: StatusCode -> 带 BEM 类名的彩色徽章 HTML 片段
- humanize_duration: 秒 -> "2 天 3 小时" / "15 分钟" / "45 秒" / "—"

颜色与显示名直接对齐 spec §3.2 表格（不在此重新枚举状态机，仅做展示映射）。
"""
from __future__ import annotations

from typing import Optional

from markupsafe import Markup

from src.models.status import StatusCode
from src.models.payment import PaymentStatus


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
    StatusCode.OFF_SHELF:            ("off-shelf",      "已下架"),
}


# 支付状态 -> (modifier, displayName)
PAYMENT_DISPLAY: dict[PaymentStatus, tuple[str, str]] = {
    PaymentStatus.PAID:    ("paid",     "已回款"),
    PaymentStatus.UNPAID:  ("unpaid",   "未回款"),
}


def status_badge(code: StatusCode | None, raw: Optional[str] = None) -> Markup:
    """渲染状态徽章 HTML。code 已知则按映射渲染；否则展示 raw（用"未知"样式）。

    返回 markupsafe.Markup 以告知 Jinja2 不要转义（autoescape=True）。
    humanize_duration 是纯文本，不应包 Markup。
    """
    if code is not None and code in STATUS_DISPLAY:
        modifier, name = STATUS_DISPLAY[code]
        return Markup(
            f'<span class="status-badge status-badge--{modifier}" '
            f'data-status-code="{code.value}">'
            f'<span class="status-badge__dot" aria-hidden="true"></span>'
            f'<span class="status-badge__name">{name}</span>'
            f"</span>"
        )
    text = raw if raw else "未知"
    return Markup(
        f'<span class="status-badge status-badge--unknown" '
        f'data-status-code="">'
        f'<span class="status-badge__dot" aria-hidden="true"></span>'
        f'<span class="status-badge__name">{text}</span>'
        f"</span>"
    )


def payment_badge(code: PaymentStatus | None, raw: Optional[str] = None) -> Markup:
    """渲染支付状态徽章。code 已知则按映射渲染；否则展示 raw("无记录"样式)。

    三种状态:
    - PAID  → 已回款(绿)
    - UNPAID → 未回款(红)
    - None + raw 为空 → 无记录(灰)
    """
    if code is not None and code in PAYMENT_DISPLAY:
        modifier, name = PAYMENT_DISPLAY[code]
        return Markup(
            f'<span class="status-badge status-badge--{modifier}" '
            f'data-payment-code="{code.value}">'
            f'<span class="status-badge__dot" aria-hidden="true"></span>'
            f'<span class="status-badge__name">{name}</span>'
            f"</span>"
        )
    if raw:
        return Markup(
            f'<span class="status-badge status-badge--unknown" '
            f'data-payment-code="">'
            f'<span class="status-badge__dot" aria-hidden="true"></span>'
            f'<span class="status-badge__name">{raw}</span>'
            f"</span>"
        )
    return Markup(
        f'<span class="status-badge status-badge--unknown" '
        f'data-payment-code="">'
        f'<span class="status-badge__dot" aria-hidden="true"></span>'
        f'<span class="status-badge__name">无记录</span>'
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