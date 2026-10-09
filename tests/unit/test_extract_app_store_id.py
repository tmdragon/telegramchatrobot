"""iOS App Store URL → App Store ID 提取测试。"""
from src.store_checker import extract_app_store_id


def test_basic_app_store_url():
    assert extract_app_store_id("https://apps.apple.com/app/id1234567890") == 1234567890


def test_app_store_url_with_country_and_slug():
    assert extract_app_store_id("https://apps.apple.com/cn/app/my-cool-game/id987654321") == 987654321


def test_app_store_url_with_query_string():
    assert extract_app_store_id("https://apps.apple.com/app/id1234567890?mt=8") == 1234567890


def test_app_store_url_with_fragment():
    assert extract_app_store_id("https://apps.apple.com/app/id1234567890#reviews") == 1234567890


def test_google_play_url_returns_none():
    assert extract_app_store_id("https://play.google.com/store/apps/details?id=com.x") is None


def test_empty_url_returns_none():
    assert extract_app_store_id("") is None


def test_non_app_store_url_returns_none():
    assert extract_app_store_id("https://example.com/foo/bar") is None


def test_id_in_path_but_no_digits_returns_none():
    assert extract_app_store_id("https://apps.apple.com/app/idsomething") is None