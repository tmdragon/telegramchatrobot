"""播报文案模板测试。"""
from datetime import datetime, timezone

from src.bot.templates import render_broadcast, render_dryrun_preview, STATUS_EMOJI
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
              StatusCode.PAID, StatusCode.FIRST_REVIEW_REJECTED, StatusCode.UNPAID]:
        assert c in STATUS_EMOJI


def test_render_broadcast_basic_shape():
    p = _project()
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False,
                            responsible_person="张三", source_sheet_name="项目主表")
    assert "PRJ-001" in text
    assert "项目一" in text
    assert "我方制作中" in text
    assert "张三" in text
    assert "项目主表" in text
    # dwell 9 小时 = 9 小时（09:18 21:00 - 09:18 12:00）
    assert "9 小时" in text
    # footer
    assert "09-18 21:00" in text


def test_render_broadcast_includes_warning_on_threshold():
    p = _project(status=StatusCode.CLIENT_REVIEW,
                 status_changed_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc))
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=True)
    assert "⚠" in text
    assert "对方验收中" in text


def test_render_broadcast_includes_recent_transition():
    p = _project(
        status=StatusCode.CLIENT_REVIEW,
        status_history=[
            (StatusCode.ORDERED, datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)),
            (StatusCode.MAKING, datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)),
            (StatusCode.CLIENT_REVIEW, datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)),
        ],
    )
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False)
    assert "我方制作中" in text  # 上一个状态
    assert "对方验收中" in text  # 当前


def test_render_broadcast_handles_missing_name_and_responsible():
    p = _project(project_name=None)
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False)
    assert "PRJ-001" in text
    assert "未命名" in text or "—" in text


def test_render_dryrun_preview_has_dryrun_prefix():
    p = _project()
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_dryrun_preview(p, m, now)
    assert "DRYRUN" in text.upper() or "试运行" in text or "预览" in text


def test_render_broadcast_dates_are_backtick_wrapped():
    """日期里的 '-' 是 MarkdownV2 保留字符；render_broadcast 必须用反引号包裹日期
    否则 Telegram 解析时会抛 BadRequest ('character \"-\" is reserved')。"""
    p = _project()
    m = _mapping()
    now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    text = render_broadcast(p, m, now, exceeded_threshold=False)
    # footer 日期必须被反引号包裹
    assert "`09-18 21:00`" in text
    # 历史流转日期同理（如果 status_history 长度 >= 2）
    p2 = _project(
        status_history=[
            (StatusCode.ORDERED, datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)),
            (StatusCode.MAKING, datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)),
        ],
    )
    text2 = render_broadcast(p2, m, now, exceeded_threshold=False)
    assert "`09-10 09:00`" in text2