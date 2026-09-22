"""Tests for SheetRepo.fetch_all recognizing new field candidates for /info."""
from unittest.mock import MagicMock
from src.sheets.repo import SheetRepo
from src.config import SpreadsheetConfig


def test_fetch_all_tags_class_name_field():
    """fetch_all 应该把'主activity类名'列标记为 recognized_as='class_name'。"""
    fake_ws = MagicMock()
    fake_ws.get_all_values.return_value = [
        ["项目编号", "状态", "项目名称", "主activity类名"],
        ["WW-001", "已上架", "Tower up up", "com.gggame.towerup.game1.MainActivity"],
    ]

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    projects = repo.fetch_all([
        SpreadsheetConfig(id="ss1", name="项目主表", role="master"),
    ])

    p = projects[0]
    class_name_field = next((f for f in p.sheets[0].fields if f.recognized_as == "class_name"), None)
    assert class_name_field is not None
    assert class_name_field.value == "com.gggame.towerup.game1.MainActivity"


def test_fetch_all_tags_sha_fields():
    """fetch_all 应该把 SHA-1 / SHA-256 / hash值 列标记。"""
    fake_ws = MagicMock()
    fake_ws.get_all_values.return_value = [
        ["项目编号", "SHA-1", "SHA-256", "hash值"],
        [
            "WW-001",
            "A1:83:FC:CE:B0:A2:EC:1B:19:41:A2:98:A9:90:4D:7C:54:54:1F:6A",
            "B5:96:58:56:34:46:CE:B9:5F:8D:41:27:E3:D2:04:AF:0A:0D:3D:9E:98:95:B2:DB:2E:72:0F:88:1F:A6:E4:F9",
            "13WJI9zm7iPkPGX8tUceqfrFP9k=",
        ],
    ]

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    projects = repo.fetch_all([
        SpreadsheetConfig(id="ss1", name="项目主表", role="master"),
    ])

    fields = {f.recognized_as: f.value for f in projects[0].sheets[0].fields}
    assert fields["sha1"] == "A1:83:FC:CE:B0:A2:EC:1B:19:41:A2:98:A9:90:4D:7C:54:54:1F:6A"
    assert fields["sha256"] == "B5:96:58:56:34:46:CE:B9:5F:8D:41:27:E3:D2:04:AF:0A:0D:3D:9E:98:95:B2:DB:2E:72:0F:88:1F:A6:E4:F9"
    assert fields["hash_value"] == "13WJI9zm7iPkPGX8tUceqfrFP9k="


def test_fetch_all_tags_privacy_policy_field():
    """fetch_all 应该把'隐私政策'列标记为 recognized_as='privacy_policy'。"""
    fake_ws = MagicMock()
    fake_ws.get_all_values.return_value = [
        ["项目编号", "隐私政策"],
        ["WW-001", "https://www.freeprivacypolicy.com/..."],
    ]

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    projects = repo.fetch_all([
        SpreadsheetConfig(id="ss1", name="项目主表", role="master"),
    ])

    fields = {f.recognized_as: f.value for f in projects[0].sheets[0].fields}
    assert fields["privacy_policy"] == "https://www.freeprivacypolicy.com/..."