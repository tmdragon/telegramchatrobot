from datetime import datetime, timezone

import markupsafe

from src.models.status import StatusCode
from src.web.filters import status_badge, humanize_duration


def test_status_badge_known_code():
    html = status_badge(StatusCode.MAKING)
    assert "我方制作中" in html
    assert "status-badge" in html


def test_status_badge_returns_markup():
    """Regression: status_badge must return a Markup object so Jinja2's
    autoescape does not HTML-escape the badge into literal text.
    See final-review whole-branch review (fix #1).
    """
    result = status_badge(StatusCode.MAKING)
    assert isinstance(result, markupsafe.Markup), (
        f"status_badge must return Markup to bypass Jinja2 autoescape; "
        f"got {type(result).__name__}"
    )
    # Markup instances expose __html__ which Jinja2 checks before escaping.
    assert hasattr(result, "__html__")


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

from src.models.payment import PaymentStatus
from src.web.filters import payment_badge


def test_payment_badge_paid():
    html = payment_badge(PaymentStatus.PAID)
    assert "已回款" in html
    assert "status-badge--paid" in html


def test_payment_badge_unpaid():
    html = payment_badge(PaymentStatus.UNPAID)
    assert "未回款" in html
    assert "status-badge--unpaid" in html


def test_payment_badge_no_record():
    html = payment_badge(None)
    assert "无记录" in html
    assert "status-badge--unknown" in html


def test_payment_badge_returns_markup():
    result = payment_badge(PaymentStatus.PAID)
    assert isinstance(result, markupsafe.Markup)


from src.models.payment import PaymentStatus, normalize_payment


def test_normalize_payment_jiesuan_aliases():
    """'已结算' / '未结算' 应该是 PAID / UNPAID 的别名(国内常见说法)。"""
    assert normalize_payment("已结算") == PaymentStatus.PAID
    assert normalize_payment("未结算") == PaymentStatus.UNPAID
    assert normalize_payment("  已结算  ") == PaymentStatus.PAID  # strip
