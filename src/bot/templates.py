"""播报 Markdown 文案模板。

render_broadcast() 产出 Telegram Markdown（PTB 客户端会再加 MarkdownV2 转义
的兼容层；这里用 PTB 默认 Markdown 即可，复杂字符如 . _ * 由 PTB 服务端校验）。

文案只保留三行（极简）：

📊 *PRJ-001 项目一*
▸ 当前状态：🟣 对方验收中

— 09-18 21:00 自动播报

超过 per_status_thresholds 阈值时 head 行追加 ⚠。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.models.project import Mapping, Project
from src.models.status import StatusCode


STATUS_EMOJI: dict[StatusCode, str] = {
    StatusCode.ORDERED: "🔵",
    StatusCode.MAKING: "🟣",
    StatusCode.CLIENT_REVIEW: "🟠",
    StatusCode.REWORK: "🟠",
    StatusCode.WAITING_AAB: "🟡",
    StatusCode.WAITING_SUBMIT: "🟡",
    StatusCode.SUBMITTING: "🟡",
    StatusCode.FIRST_REVIEW_PASSED: "🟡",
    StatusCode.FIRST_REVIEW_REJECTED: "🔴",
    StatusCode.SECOND_REVIEW: "🟡",
    StatusCode.REMAKING: "🟠",
    StatusCode.PUBLISHED: "🟢",
    StatusCode.PAID: "🟢",
    StatusCode.UNPAID: "🔴",
    StatusCode.OFF_SHELF: "⚫",
}

STATUS_DISPLAY_CN: dict[StatusCode, str] = {
    StatusCode.ORDERED: "对方下单",
    StatusCode.MAKING: "我方制作中",
    StatusCode.CLIENT_REVIEW: "对方验收中",
    StatusCode.REWORK: "返工中",
    StatusCode.WAITING_AAB: "等待AAB包",
    StatusCode.WAITING_SUBMIT: "等待提审",
    StatusCode.SUBMITTING: "提审中",
    StatusCode.FIRST_REVIEW_PASSED: "一审通过",
    StatusCode.FIRST_REVIEW_REJECTED: "一审打回",
    StatusCode.SECOND_REVIEW: "复审中",
    StatusCode.REMAKING: "我方重做中",
    StatusCode.PUBLISHED: "已发布",
    StatusCode.PAID: "对方已回款",
    StatusCode.UNPAID: "对方未回款",
    StatusCode.OFF_SHELF: "已下架",
}


def status_display_text(project: Project) -> str:
    """返回项目状态的展示文本：sheet 原文本 → STATUS_DISPLAY_CN → 状态码本身。"""
    if project.status_raw:
        return project.status_raw
    if project.status is not None:
        return STATUS_DISPLAY_CN.get(project.status, project.status.value)
    return ""


def _format_status_line(project: Project) -> str:
    if project.status is None and not project.status_raw:
        return "▸ 当前状态：未知"
    emoji = STATUS_EMOJI.get(project.status, "⚪") if project.status else "⚪"
    text = status_display_text(project) or (project.status.value if project.status else "未知")
    return f"▸ 当前状态：{emoji} {text}"


def render_broadcast(
    project: Project,
    mapping: Mapping,
    now: datetime,
    exceeded_threshold: bool,
    *,
    responsible_person: Optional[str] = None,
    source_sheet_name: Optional[str] = None,
) -> str:
    name = project.project_name or "（未命名）"
    head = f"📊 *`{project.project_id}` {name}*"
    if exceeded_threshold:
        head += " ⚠"
    lines = [
        head,
        _format_status_line(project),
        "",
        f"— `{now.strftime('%m-%d %H:%M')}` 自动播报",
    ]
    return "\n".join(lines)


def render_dryrun_preview(project: Project, mapping: Mapping, now: datetime) -> str:
    body = render_broadcast(project, mapping, now, exceeded_threshold=False)
    return f"🧪 *DRYRUN 预览*\n```\n{body}\n```"