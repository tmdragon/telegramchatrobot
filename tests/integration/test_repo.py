from datetime import datetime, timezone
from unittest.mock import MagicMock
from src.config import SpreadsheetConfig
from src.sheets.repo import SheetRepo


def _make_fake_worksheet(rows: list[list]) -> MagicMock:
    ws = MagicMock()
    ws.title = "项目主表"
    ws.get_all_values.return_value = rows
    return ws


def test_fetch_all_groups_rows_by_project_id():
    fake_client = MagicMock()
    fake_ws = _make_fake_worksheet([
        ["项目编号", "项目名", "状态"],          # 表头
        ["PRJ-001", "项目一", "制作中"],
        ["PRJ-002", "项目二", "验收中"],
    ])
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    ss = [SpreadsheetConfig(id="ss1", name="项目主表", role="master")]
    projects = repo.fetch_all(ss)

    assert len(projects) == 2
    ids = sorted(p.project_id for p in projects)
    assert ids == ["PRJ-001", "PRJ-002"]
    p1 = next(p for p in projects if p.project_id == "PRJ-001")
    assert p1.project_name == "项目一"
    from src.models.status import StatusCode
    assert p1.status == StatusCode.MAKING
    assert len(p1.sheets) == 1
    assert len(p1.sheets[0].fields) == 3


def test_fetch_all_multiple_sheets_same_project_merged():
    fake_client = MagicMock()
    fake_ws1 = _make_fake_worksheet([
        ["项目编号", "项目名", "状态"],
        ["PRJ-001", "项目一", "制作中"],
    ])
    fake_ws1.title = "项目主表"
    fake_ws2 = _make_fake_worksheet([
        ["项目编号", "预算", "已花费"],
        ["PRJ-001", "100000", "75000"],
    ])
    fake_ws2.title = "财务子表"

    # 两次 open_by_key 返回不同 spreadsheet
    fake_client.open_by_key.side_effect = [
        MagicMock(worksheet=MagicMock(return_value=fake_ws1)),
        MagicMock(worksheet=MagicMock(return_value=fake_ws2)),
    ]

    repo = SheetRepo(fake_client)
    ss = [
        SpreadsheetConfig(id="ss1", name="项目主表", role="master"),
        SpreadsheetConfig(id="ss2", name="财务子表", role="detail"),
    ]
    projects = repo.fetch_all(ss)

    assert len(projects) == 1
    p = projects[0]
    assert p.project_id == "PRJ-001"
    assert len(p.sheets) == 2  # 两张表的视图
    sheet_names = sorted(s.sheet_name for s in p.sheets)
    assert sheet_names == ["财务子表", "项目主表"]


def test_fetch_all_empty_project_id_rows_skipped():
    fake_client = MagicMock()
    fake_ws = _make_fake_worksheet([
        ["项目编号", "状态"],
        ["", "制作中"],          # 空项目编号行：跳过
        ["PRJ-001", "制作中"],
    ])
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    ss = [SpreadsheetConfig(id="ss1", name="项目主表", role="master")]
    projects = repo.fetch_all(ss)

    assert len(projects) == 1
    assert projects[0].project_id == "PRJ-001"


def test_fetch_all_captures_status_raw_text():
    """SheetRepo.fetch_all 必须把状态列原文本存进 Project.status_raw。"""
    fake_client = MagicMock()
    fake_ws = _make_fake_worksheet([
        ["项目编号", "项目名", "状态"],
        ["PRJ-001", "项目一", "制作中"],   # 中文别名
        ["PRJ-002", "项目二", "MAKING"],   # 英文 code
        ["PRJ-003", "项目三", "  验收中  "],  # 前后空格
        ["PRJ-004", "项目四", ""],          # 空
    ])
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    ss = [SpreadsheetConfig(id="ss1", name="项目主表", role="master")]
    projects = repo.fetch_all(ss)

    by_id = {p.project_id: p for p in projects}
    assert by_id["PRJ-001"].status_raw == "制作中"
    assert by_id["PRJ-002"].status_raw == "MAKING"
    assert by_id["PRJ-003"].status_raw == "验收中"  # strip 后
    assert by_id["PRJ-004"].status_raw is None  # 空 → None
