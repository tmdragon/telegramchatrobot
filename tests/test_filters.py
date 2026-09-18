from datetime import datetime, timezone

from src.models.status import StatusCode
from src.web.filters import status_badge, humanize_duration


def test_status_badge_known_code():
    html = status_badge(StatusCode.MAKING)
    assert "我方制作中" in html
    assert "status-badge" in html


def test_status_badge_unknown_renders_raw():
    html = status_badge(None, raw="随便写的状态")
    assert "随便写的状态" in html
    assert "unknown" in html or "未知" in html


def test_humanize_duration_days_hours():
    # 2 天 3 小时 = 2 * 86400 + 3 * 3600 = 183600
    assert humanize_duration(183600) == "2 天 3 小时"


def test_humanize_duration_minutes():
    assert humanize_duration(15 * 60) == "15 分钟"


def test_humanize_duration_seconds():
    assert humanize_duration(45) == "45 秒"


def test_humanize_duration_zero():
    assert humanize_duration(0) == "0 秒"


def test_humanize_duration_none():
    assert humanize_duration(None) == "—"


def test_humanize_duration_negative():
    assert humanize_duration(-10) == "—"