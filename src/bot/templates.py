"""播报 Markdown 文案模板。

render_broadcast() 产出 Telegram Markdown（PTB 客户端会再加 MarkdownV2 转义
的兼容层；这里用 PTB 默认 Markdown 即可，复杂字符如 . _ * 由 PTB 服务端校验）。

spec §6.4 文案示例：

📊 *PRJ-001 项目一*
▸ 当前状态：🟣 对方验收中（已停留 2 天 3 小时）
▸ 最近流转：09-16 18:00 由 `我方制作中` → `对方验收中`
▸ 责任人：张三（来自表"项目主表"）

— 09-18 21:00 自动播报

异常播报前缀 + ⚠ 超过阈值。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.models.project import Mapping, Project
from src.models.status import StatusCode
from src.web.filters import humanize_duration


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


def _format_status_line(project: Project, now: datetime) -> str:
    if project.status is None:
        return "▸ 当前状态：未知"
    emoji = STATUS_EMOJI.get(project.status, "⚪")
    cn = STATUS_DISPLAY_CN.get(project.status, project.status.value)
    dwell = 0
    if project.status_changed_at:
        dwell = max(0, int((now - project.status_changed_at).total_seconds()))
    return f"▸ 当前状态：{emoji} {cn}（已停留 {humanize_duration(dwell)}）"


def _format_transition_line(project: Project) -> str:
    """最近流转：status_history 最后两条。"""
    hist = list(project.status_history or [])
    if len(hist) < 2:
        return "▸ 最近流转：—"
    prev_code, prev_at = hist[-2]
    curr_code, _ = hist[-1]
    prev_cn = STATUS_DISPLAY_CN.get(prev_code, prev_code.value)
    curr_cn = STATUS_DISPLAY_CN.get(curr_code, curr_code.value)
    return (
        f"▸ 最近流转：`{prev_at.strftime('%m-%d %H:%M')}` "
        f"由 `{prev_cn}` → `{curr_cn}`"
    )


def _format_responsible_line(
    responsible_person: Optional[str], source_sheet_name: Optional[str]
) -> str:
    if not responsible_person and not source_sheet_name:
        return "▸ 责任人：—"
    if responsible_person and source_sheet_name:
        return f"▸ 责任人：{responsible_person}（来自表「{source_sheet_name}」）"
    return f"▸ 责任人：{responsible_person or '—'}"


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
        _format_status_line(project, now),
        _format_transition_line(project),
        _format_responsible_line(responsible_person, source_sheet_name),
        "",
        f"— `{now.strftime('%m-%d %H:%M')}` 自动播报",
    ]
    return "\n".join(lines)


def render_dryrun_preview(project: Project, mapping: Mapping, now: datetime) -> str:
    body = render_broadcast(project, mapping, now, exceeded_threshold=False)
    return f"🧪 *DRYRUN 预览*\n```\n{body}\n```"