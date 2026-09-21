"""播报文案模板测试。"""
from datetime import datetime, timezone

from src.bot.templates import (
    BroadcastTrigger,
    render_broadcast,
    render_dryrun_preview,
    STATUS_EMOJI,
    TRIGGER_LABEL,
)
from src.models.project import Mapping, Project
from src.models.status import StatusCode


def _project(**kw):
    base = dict(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        status_history=[(StatusCode.ORDERED, datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc))],
        sheets=[],
    )
    base.update(kw)
    return Project(**base)


def _mapping(**kw):
    base = dict(
        project_id="PRJ-001", chat_id="123456",
        note="", enabled=True,
        last_broadcast_at=None, last_broadcast_status=None, last_error=None,
    )
    base.update(kw)
    return Mapping(**base)


def test_status_emoji_table_covers_common_codes():
    for c in [StatusCode.MAKING, StatusCode.CLIENT_REVIEW, StatusCode.PUBLISHED,
              StatusCode.OFF_SHELF, StatusCode.FIRST_REVIEW_REJECTED]:
        assert c in STATUS_EMOJI


def test_render_broadcast_basic_shape():
    """极简模板：仅 head + 当前状态 + 包名 + footer。"""
    p = _project()
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False,
                            responsible_person="张三", source_sheet_name="项目主表")
    assert "PRJ-001" in text
    assert "项目一" in text
    assert "我方制作中" in text
    # 包名：默认 None → 显示 "—"
    assert "—`" in text  # 占位
    assert "包名" in text
    # 责任人、来源表不再出现在播报里
    assert "张三" not in text
    assert "项目主表" not in text
    # 没有 dwell 提示
    assert "已停留" not in text
    assert "9 小时" not in text
    # 没有最近流转行
    assert "最近流转" not in text
    # 没有责任人行
    assert "责任人" not in text
    # footer
    assert "09-18 21:00" in text


def test_render_broadcast_includes_package_name():
    p = _project(package_name="com.example.game")
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False)
    assert "com.example.game" in text


def test_render_broadcast_includes_warning_on_threshold():
    p = _project(status=StatusCode.CLIENT_REVIEW,
                 status_changed_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc))
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=True)
    assert "⚠" in text
    assert "对方验收中" in text


def test_render_broadcast_handles_missing_name():
    p = _project(project_name=None)
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False)
    assert "PRJ-001" in text
    assert "未命名" in text


def test_render_dryrun_preview_has_dryrun_prefix():
    p = _project()
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_dryrun_preview(p, m, now)
    assert "DRYRUN" in text.upper() or "试运行" in text or "预览" in text


def test_render_broadcast_footer_date_is_backtick_wrapped():
    """日期里的 '-' 是 MarkdownV2 保留字符；footer 日期必须用反引号包裹。"""
    p = _project()
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False)
    assert "`09-18 21:00`" in text


def test_render_broadcast_prefers_status_raw_text_over_canonical():
    """如果 Project.status_raw 已设置，播报用 sheet 原文本，不用 STATUS_DISPLAY_CN。"""
    p = _project(status=StatusCode.MAKING, status_raw="制作中")
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False)
    assert "▸ 当前状态" in text
    status_line = next(l for l in text.splitlines() if l.startswith("▸ 当前状态"))
    assert "制作中" in status_line
    assert "我方制作中" not in status_line


def test_render_broadcast_status_raw_english_text_preserved():
    """sheet 写英文 'MAKING' 时也原样显示。"""
    p = _project(status=StatusCode.MAKING, status_raw="MAKING")
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False)
    status_line = next(l for l in text.splitlines() if l.startswith("▸ 当前状态"))
    assert "MAKING" in status_line


def test_render_broadcast_falls_back_to_canonical_when_no_status_raw():
    """status_raw 为空时 fallback 到 STATUS_DISPLAY_CN。"""
    p = _project(status=StatusCode.MAKING, status_raw=None)
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False)
    status_line = next(l for l in text.splitlines() if l.startswith("▸ 当前状态"))
    assert "我方制作中" in status_line


# ---------- 播报触发源（"自动" vs "状态更新监测"）----------

def test_trigger_label_table_covers_known_triggers():
    """所有 BroadcastTrigger 必须映射到一个非空中文文案。"""
    assert BroadcastTrigger.SCHEDULED in TRIGGER_LABEL
    assert BroadcastTrigger.STATUS_CHANGE in TRIGGER_LABEL
    # SCHEDULED 应该是"定时播报"，STATUS_CHANGE 应该是"状态变更"类的字样
    assert "播报" in TRIGGER_LABEL[BroadcastTrigger.SCHEDULED] or \
           "自动" in TRIGGER_LABEL[BroadcastTrigger.SCHEDULED]
    assert "状态" in TRIGGER_LABEL[BroadcastTrigger.STATUS_CHANGE]
    # 不再硬编码 "自动播报" 当成唯一文案
    assert "自动播报" not in TRIGGER_LABEL[BroadcastTrigger.STATUS_CHANGE]


def test_render_broadcast_footer_label_scheduled():
    """broadcast_all / cron 默认 SCHEDULED → footer 用"定时播报"类文案，不要再说"自动播报"。"""
    p = _project()
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False,
                            trigger=BroadcastTrigger.SCHEDULED)
    # 最后一行的关键文案（不严格匹配具体文字，只要不含旧的"自动播报"）
    last_line = text.strip().splitlines()[-1]
    assert "自动播报" not in text
    # 必须包含 TRIGGER_LABEL 中的文案
    assert TRIGGER_LABEL[BroadcastTrigger.SCHEDULED] in last_line


def test_render_broadcast_footer_label_status_change():
    """事件驱动（status update 检测触发）→ footer 用"状态变更"类文案。"""
    p = _project()
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False,
                            trigger=BroadcastTrigger.STATUS_CHANGE)
    last_line = text.strip().splitlines()[-1]
    assert "自动播报" not in text
    assert TRIGGER_LABEL[BroadcastTrigger.STATUS_CHANGE] in last_line
    # 且必须与 SCHEDULED 标签不同（这才算"区分两个事件"）
    assert TRIGGER_LABEL[BroadcastTrigger.STATUS_CHANGE] != TRIGGER_LABEL[BroadcastTrigger.SCHEDULED]