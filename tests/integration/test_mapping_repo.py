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


def test_load_all_grouped_aggregates_by_chat_id():
    """load_all_grouped 应该按 chat_id 聚合,每个唯一 chat_id 一组。"""
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    rows = [
        # 同 chat_id 的两个项目 → 一组;note 取首个非空
        ["PRJ-001", "-1001", "一群", "TRUE", ""],
        ["PRJ-002", "-1001", "",       "FALSE", ""],
        # 不同 chat_id → 两组
        ["PRJ-003", "-1002", "二群", "TRUE", ""],
    ]
    fake_ws = _make_ws(headers, rows)
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    groups = repo.load_all_grouped()

    chat_ids = [g.chat_id for g in groups]
    assert chat_ids == ["-1001", "-1002"]

    g1 = groups[0]
    assert sorted(g1.projects) == ["PRJ-001", "PRJ-002"]
    assert g1.note == "一群"  # 首个非空备注
    # 部分启用 = 'partial'
    assert g1.enabled_state == "partial"

    g2 = groups[1]
    assert g2.projects == ["PRJ-003"]
    assert g2.enabled_state == "all"


def test_update_group_updates_all_mappings_with_chat_id():
    """update_group 应该把所有该 chat_id 的 mapping 的 note/enabled 都更新。"""
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    rows = [
        ["PRJ-001", "-1001", "old", "TRUE", ""],
        ["PRJ-002", "-1001", "old", "TRUE", ""],
        ["PRJ-003", "-1002", "keep", "TRUE", ""],  # 不同 chat_id,不该被影响
    ]
    fake_ws = _make_ws(headers, rows)
    # find() 按值查;按测试 stub 总是返回 row 2,这里用更精确的 mock
    def _find(value):
        # 找 PRJ-001 → row 2;PRJ-002 → row 3;PRJ-003 → row 4
        m = {"PRJ-001": 2, "PRJ-002": 3, "PRJ-003": 4}
        return MagicMock(row=m.get(value))
    fake_ws.find.side_effect = _find
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    repo.update_group("-1001", note="new", enabled=False)

    # PRJ-001 和 PRJ-002 应该被更新;PRJ-003 不动
    update_calls = [(c.args[0], c.args[1], c.args[2]) for c in fake_ws.update_cell.call_args_list]
    # 注列(3)和 启用列(4)
    assert (2, 3, "new") in update_calls  # PRJ-001 note
    assert (2, 4, "FALSE") in update_calls  # PRJ-001 enabled
    assert (3, 3, "new") in update_calls  # PRJ-002 note
    assert (3, 4, "FALSE") in update_calls  # PRJ-002 enabled
    # PRJ-003 不应被调用
    prj003_calls = [c for c in update_calls if c[0] == 4]
    assert prj003_calls == []


def test_disable_group_soft_deletes_all_mappings_with_chat_id():
    """disable_group 把所有该 chat_id 的 mapping 的 enabled 设为 FALSE。"""
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    rows = [
        ["PRJ-001", "-1001", "", "TRUE", ""],
        ["PRJ-002", "-1001", "", "TRUE", ""],
    ]
    fake_ws = _make_ws(headers, rows)
    def _find(value):
        return MagicMock(row={"PRJ-001": 2, "PRJ-002": 3}.get(value))
    fake_ws.find.side_effect = _find
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    repo.disable_group("-1001")

    update_calls = [(c.args[0], c.args[1], c.args[2]) for c in fake_ws.update_cell.call_args_list]
    assert (2, 4, "FALSE") in update_calls
    assert (3, 4, "FALSE") in update_calls


def test_create_group_inserts_first_mapping():
    """create_group 应该 append 一条 mapping。"""
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    fake_ws = _make_ws(headers, [])
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    repo.create_group(chat_id="-1001", project_id="PRJ-001", note="一群", enabled=True)

    fake_ws.append_row.assert_called_once()
    args = fake_ws.append_row.call_args[0][0]
    assert args[0] == "PRJ-001"
    assert args[1] == "-1001"
    assert args[2] == "一群"
    assert args[3] == "TRUE"


def test_create_group_rejects_duplicate_chat_id():
    """create_group 如果 chat_id 已存在,应抛 ValueError。"""
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    rows = [["PRJ-001", "-1001", "", "TRUE", ""]]
    fake_ws = _make_ws(headers, rows)
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    import pytest
    with pytest.raises(ValueError, match="already exists"):
        repo.create_group(chat_id="-1001", project_id="PRJ-002", note="")
