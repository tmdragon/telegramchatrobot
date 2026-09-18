from unittest.mock import MagicMock
from src.models.project import Mapping
from src.sheets.mapping_repo import MappingRepo


def _make_ws(headers: list[str], rows: list[list]):
    ws = MagicMock()
    ws.title = "项目群映射"
    ws.get_all_values.return_value = [headers] + rows
    ws.find.return_value = MagicMock(row=2)  # 默认找到第 2 行（第一行是表头）
    return ws


def test_load_all_parses_rows():
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    rows = [
        ["PRJ-001", "-1001234567890", "一群", "TRUE", "2026-09-18 21:00"],
        ["PRJ-002", "-1009876543210", "二群", "FALSE", ""],
    ]
    fake_ws = _make_ws(headers, rows)
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    mappings = repo.load_all()

    assert len(mappings) == 2
    assert mappings[0].project_id == "PRJ-001"
    assert mappings[0].chat_id == "-1001234567890"
    assert mappings[0].enabled is True
    assert mappings[1].enabled is False


def test_upsert_inserts_new_row():
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    fake_ws = _make_ws(headers, [])
    fake_ws.find.return_value = None  # 找不到 → append
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    m = Mapping(project_id="PRJ-001", chat_id="-100123", note="一群")
    repo.upsert(m)

    fake_ws.append_row.assert_called_once()
    args = fake_ws.append_row.call_args[0][0]
    assert args[0] == "PRJ-001"
    assert args[1] == "-100123"


def test_upsert_updates_existing_row():
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    fake_ws = _make_ws(headers, [["PRJ-001", "-100", "old", "TRUE", ""]])
    fake_ws.find.return_value = MagicMock(row=2)
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    m = Mapping(project_id="PRJ-001", chat_id="-100", note="new note", enabled=False)
    repo.upsert(m)

    fake_ws.update_cell.assert_called()
    # 验证备注列（index 3，1-indexed）被更新
    calls = [c for c in fake_ws.update_cell.call_args_list if c[0][2] == "new note"]
    assert len(calls) >= 1
    fake_ws.update_cell.assert_any_call(2, 3, "new note")


def test_delete_soft_deletes():
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    fake_ws = _make_ws(headers, [["PRJ-001", "-100", "", "TRUE", ""]])
    fake_ws.find.return_value = MagicMock(row=2)
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    repo.delete("PRJ-001")

    # 软删除：把"是否启用"列（index 4）改为 FALSE
    fake_ws.update_cell.assert_any_call(2, 4, "FALSE")
