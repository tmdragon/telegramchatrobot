"""Tests for HeaderDetector field recognition + 确认新候选列常量已加入 parser。"""
from src.sheets.parser import (
    HeaderDetector,
    CLASS_NAME_CANDIDATES,
    PRIVACY_POLICY_CANDIDATES,
    SHA1_CANDIDATES,
    SHA256_CANDIDATES,
    HASH_CANDIDATES,
)


def test_new_candidates_constants_exist():
    """parser.py 里需要新加这些候选列常量(给 /info 命令用)。"""
    # 每个常量必须存在且非空
    assert isinstance(CLASS_NAME_CANDIDATES, list) and len(CLASS_NAME_CANDIDATES) > 0
    assert isinstance(PRIVACY_POLICY_CANDIDATES, list) and len(PRIVACY_POLICY_CANDIDATES) > 0
    assert isinstance(SHA1_CANDIDATES, list) and len(SHA1_CANDIDATES) > 0
    assert isinstance(SHA256_CANDIDATES, list) and len(SHA256_CANDIDATES) > 0
    assert isinstance(HASH_CANDIDATES, list) and len(HASH_CANDIDATES) > 0


def test_class_name_candidates_match_user_columns():
    """'主activity类名' 必须被识别为 class_name。"""
    assert "主activity类名" in CLASS_NAME_CANDIDATES


def test_privacy_policy_candidates_match_user_columns():
    assert "隐私政策" in PRIVACY_POLICY_CANDIDATES


def test_sha1_candidates_match_user_columns():
    assert "SHA-1" in SHA1_CANDIDATES


def test_sha256_candidates_match_user_columns():
    assert "SHA-256" in SHA256_CANDIDATES


def test_hash_candidates_match_user_columns():
    assert "hash值" in HASH_CANDIDATES


# HeaderDetector 基础功能(已有常量)
def test_detects_known_columns_existing():
    """回归:现有常量识别仍然正确。"""
    from src.sheets.parser import (
        PROJECT_ID_CANDIDATES,
        STATUS_CANDIDATES,
        PROJECT_NAME_CANDIDATES,
        PACKAGE_NAME_CANDIDATES,
        LAUNCH_REGION_CANDIDATES,
    )

    h = HeaderDetector(["项目编号", "状态", "项目名称", "包名", "上架地区"])
    assert h.find_column(PROJECT_ID_CANDIDATES) == 1
    assert h.find_column(STATUS_CANDIDATES) == 2
    assert h.find_column(PROJECT_NAME_CANDIDATES) == 3
    assert h.find_column(PACKAGE_NAME_CANDIDATES) == 4
    assert h.find_column(LAUNCH_REGION_CANDIDATES) == 5


def test_returns_none_for_missing_column():
    """如果 sheet 缺这一列,find_column 返回 None(便于 caller 知道缺)。"""
    h = HeaderDetector(["项目编号", "包名"])
    assert h.find_column(CLASS_NAME_CANDIDATES) is None
    assert h.find_column(SHA1_CANDIDATES) is None
    assert h.find_column(HASH_CANDIDATES) is None