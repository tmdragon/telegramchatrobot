from src.models.status import StatusCode, normalize, ALIASES


def test_aliases_has_13_entries():
    """PAID/UNPAID 已迁出到 PaymentStatus，StatusCode 别名表只剩 13 条。"""
    assert len(ALIASES) == 13


def test_off_shelf_aliases():
    assert normalize("已下架") == StatusCode.OFF_SHELF
    assert normalize("下架") == StatusCode.OFF_SHELF
    assert normalize("已下线") == StatusCode.OFF_SHELF
    assert normalize("OFF_SHELF") == StatusCode.OFF_SHELF


def test_normalize_exact_code():
    assert normalize("MAKING") == StatusCode.MAKING


def test_normalize_chinese_alias():
    assert normalize("制作中") == StatusCode.MAKING
    assert normalize("我方制作中") == StatusCode.MAKING


def test_normalize_case_insensitive():
    assert normalize("making") == StatusCode.MAKING
    assert normalize("  Making  ") == StatusCode.MAKING


def test_normalize_first_review_alias():
    assert normalize("一审通过") == StatusCode.FIRST_REVIEW_PASSED
    assert normalize("第一轮通过") == StatusCode.FIRST_REVIEW_PASSED


def test_normalize_unknown_returns_none():
    assert normalize("随意写的状态") is None
    assert normalize(None) is None
    assert normalize("") is None