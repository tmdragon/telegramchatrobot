from unittest.mock import MagicMock
from src.models.project import Mapping
from src.sheets.mapping_repo import MappingRepo

HEADERS = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]


class _FakeCell:
    def __init__(self, row, col, value):
        self.row = row
        self.col = col
        self.value = value


class _FakeWorksheet:
    """模拟 gspread.Worksheet 的关键行为(与 gspread 6.x 一致)。

    - find(query):整表按行优先扫描,**精确**匹配(大小写敏感),返回首个命中单元格;
      找不到返回 None。这是 gspread 的真实语义 —— 不是"包含",也不限定列。
    - get_all_values():当前表内容
    - update_cell(row, col, value):1-indexed 写入,落到内存表(便于断言最终状态)
    - append_row(row):追加到末尾

    之前的测试用 MagicMock 把 find() 固定成"总能找对行",恰好掩盖了
    "整表首个匹配"定位到别的行的坑。
    """

    def __init__(self, headers, rows):
        self.title = "项目群映射"
        self._rows = [list(headers)] + [list(r) for r in rows]

    def get_all_values(self):
        return [list(r) for r in self._rows]

    def find(self, query, in_row=None, in_column=None, case_sensitive=True):
        for ri, row in enumerate(self._rows, start=1):
            for ci, val in enumerate(row, start=1):
                text = "" if val is None else str(val)
                if case_sensitive:
                    hit = text == query
                else:
                    hit = text.casefold() == query.casefold()
                if hit:
                    return _FakeCell(ri, ci, text)
        return None

    def update_cell(self, row, col, value):
        while len(self._rows) < row:
            self._rows.append([])
        target = self._rows[row - 1]
        while len(target) < col:
            target.append("")
        target[col - 1] = value

    def append_row(self, row_data, **kwargs):
        self._rows.append(list(row_data))


def _make_fake_repo(ws):
    client = MagicMock()
    client.open.return_value.worksheet.return_value = ws
    return MappingRepo(client)


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


def test_load_all_keeps_mappings_with_empty_project_id():
    """load_all 应该保留空 project_id 的行(纯群映射,没关联项目)。
    之前 if not pid: continue 会跳过这种行;现在保留以便 load_all_grouped 能聚合。
    """
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    rows = [
        ["",       "-1001", "纯群映射", "TRUE", ""],  # 空 project_id → 保留
        ["PRJ-001", "-1001", "",         "TRUE", ""],  # 正常映射
        ["",        "-1002", "",          "TRUE", ""],  # 另一个空映射
    ]
    fake_ws = _make_ws(headers, rows)
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    mappings = repo.load_all()

    # 不该跳过任何行
    assert len(mappings) == 3
    # 空 project_id 也被保留
    pids = [m.project_id for m in mappings]
    assert "" in pids


def test_create_group_with_empty_project_id():
    """create_group 接受空 project_id,只创建纯群映射(不关联任何项目)。"""
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    fake_ws = _make_ws(headers, [])
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    repo.create_group(chat_id="-1001", project_id="", note="BMW 客户群")

    fake_ws.append_row.assert_called_once()
    args = fake_ws.append_row.call_args[0][0]
    assert args[0] == ""              # project_id 列空
    assert args[1] == "-1001"
    assert args[2] == "BMW 客户群"


def test_load_all_grouped_includes_groups_with_no_projects():
    """load_all_grouped 应该包含纯群映射(没有任何 project_id 关联)。"""
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    rows = [
        ["",         "-1001", "BMW 客户群", "TRUE", ""],
        ["PRJ-001", "-1002", "Audi 客户",   "TRUE", ""],
    ]
    fake_ws = _make_ws(headers, rows)
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    groups = repo.load_all_grouped()

    chat_ids = sorted(g.chat_id for g in groups)
    assert chat_ids == ["-1001", "-1002"]

    g1 = next(g for g in groups if g.chat_id == "-1001")
    assert g1.projects == []  # 纯群映射,无关联项目


def test_set_group_projects_adds_and_removes():
    """set_group_projects 应该把该 chat_id 下 enabled 的 mappings 同步成给定集合。
    - desired - current:新项目,要创建(或重新启用已停用的)
    - current - desired:多余项目,停用(enabled=false)
    """
    headers = ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"]
    rows = [
        # 当前 enabled:PRJ-001, PRJ-002
        ["PRJ-001", "-1001", "ok", "TRUE",  ""],
        ["PRJ-002", "-1001", "ok", "TRUE",  ""],
        # 已停用:PRJ-X(disabled,user 之前移除了)
        ["PRJ-X",   "-1001", "ok", "FALSE", ""],
        # 不属于本群的不动
        ["PRJ-003", "-1002", "other", "TRUE", ""],
    ]
    fake_ws = _make_ws(headers, rows)
    def _find(value):
        rows_idx = {"PRJ-001": 2, "PRJ-002": 3, "PRJ-X": 4, "PRJ-003": 5}
        return MagicMock(row=rows_idx.get(value))
    fake_ws.find.side_effect = _find
    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = MappingRepo(fake_client)
    # desired = PRJ-001, PRJ-002, PRJ-003(新增 PRJ-003;PRJ-X 保持 disabled;PRJ-001/002 不动)
    repo.set_group_projects("-1001", project_ids=["PRJ-001", "PRJ-002", "PRJ-003"])

    # PRJ-X 行应该被写 FALSE(已经 FALSE,可能再写一次;无害)
    # PRJ-003 应该被追加(append_row 调一次)
    fake_ws.append_row.assert_called_once()
    args = fake_ws.append_row.call_args[0][0]
    assert args[0] == "PRJ-003"
    assert args[1] == "-1001"


# ---------- 移除项目必须落在「本群」那一行 ----------

def test_set_group_projects_disables_only_this_chats_row():
    """同一个项目在两个群各有一行时,移除只应停用本群那一行。

    之前用 ws.find(project_id)(整表首个精确匹配)定位行,会写到别的群的行上:
    本群的行原封不动 → 前端看着像"移除没生效"。
    """
    ws = _FakeWorksheet(HEADERS, [
        ["PRJ-001", "-1001", "一群", "TRUE", ""],
        ["PRJ-001", "-1002", "二群", "TRUE", ""],
    ])
    repo = _make_fake_repo(ws)

    repo.set_group_projects("-1002", project_ids=[])

    rows = ws.get_all_values()
    assert rows[2][3] == "FALSE", "本群(-1002)那一行应被停用"
    assert rows[1][3] == "TRUE", "别的群(-1001)的行不应被误改"


def test_set_group_projects_removes_project_with_padded_cell():
    """sheet 单元格里的项目编号带尾随空格时也要能停用。

    load_all() 会 strip,所以群页面上看到的是干净的 "PRJ-001";
    但 ws.find("PRJ-001") 是精确匹配,带空格就找不到 → 静默不写 → 移除没生效。
    """
    ws = _FakeWorksheet(HEADERS, [
        ["PRJ-001 ", "-1001", "一群", "TRUE", ""],
    ])
    repo = _make_fake_repo(ws)

    repo.set_group_projects("-1001", project_ids=[])

    assert ws.get_all_values()[1][3] == "FALSE"


def test_set_group_projects_reenables_this_chats_row():
    """重新关联已停用的项目时,启用的应该是本群那一行。"""
    ws = _FakeWorksheet(HEADERS, [
        ["PRJ-001", "-1001", "一群", "FALSE", ""],
        ["PRJ-001", "-1002", "二群", "TRUE",  ""],
    ])
    repo = _make_fake_repo(ws)

    repo.set_group_projects("-1001", project_ids=["PRJ-001"])

    rows = ws.get_all_values()
    assert rows[1][3] == "TRUE", "本群(-1001)那一行应被启用"
    assert rows[2][3] == "TRUE", "别的群(-1002)的行不应被误改"


def test_set_group_projects_does_not_duplicate_row_when_re_adding():
    """同一项目在本群停用后再加回来,应该重新启用而不是追加重复行。"""
    ws = _FakeWorksheet(HEADERS, [
        ["PRJ-001", "-1001", "一群", "FALSE", ""],
    ])
    repo = _make_fake_repo(ws)

    repo.set_group_projects("-1001", project_ids=["PRJ-001"])

    assert len(ws.get_all_values()) == 2, "不应该追加新行"
    assert ws.get_all_values()[1][3] == "TRUE"
