from src.models.status import StatusCode, normalize, ALIASES


def test_aliases_has_15_entries():
    assert len(ALIASES) == 15


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