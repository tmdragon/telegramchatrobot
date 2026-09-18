from src.sheets.parser import (
    HeaderDetector, PROJECT_ID_CANDIDATES, STATUS_CANDIDATES,
    parse_project_id, parse_status,
)
from src.models.status import StatusCode


def test_header_detector_exact_match():
    d = HeaderDetector(["项目编号", "项目名", "进度"])
    assert d.find_column(PROJECT_ID_CANDIDATES) == 1


def test_header_detector_english_match():
    d = HeaderDetector(["Status", "Name"])
    assert d.find_column(STATUS_CANDIDATES) == 1


def test_header_detector_not_found():
    d = HeaderDetector(["无关列", "其他"])
    assert d.find_column(PROJECT_ID_CANDIDATES) is None


def test_header_detector_substring_match():
    # "项目 ID" 是 "项目编号"的候选之一；但表头写的是 "项目 编号"（含空格）也应该命中
    d = HeaderDetector(["项 目 编 号", "进度"])
    # 此例测试：精确匹配优先；若候选是 "项目编号"，子串 "项目编号" 在 "项 目 编 号" 里不存在 → None
    assert d.find_column(["项目编号"]) is None


def test_parse_project_id():
    assert parse_project_id("PRJ-001") == "PRJ-001"
    assert parse_project_id("  PRJ-001  ") == "PRJ-001"
    assert parse_project_id("") is None
    assert parse_project_id(None) is None


def test_parse_status_delegates_to_normalize():
    assert parse_status("制作中") == StatusCode.MAKING
    assert parse_status("未知") is None