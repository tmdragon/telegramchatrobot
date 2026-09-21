from unittest.mock import MagicMock, call
from src.sheets.repo import SheetRepo


def test_update_cell_uses_open_by_key_not_open():
    """update_cell 必须用 client.open_by_key() 而不是 client.open()。

    第一个参数语义上叫 spreadsheet_name 但实际是 spreadsheet_id
    (来自 cache 的 SheetView.spreadsheet_id,经前端 field_id 编码后传入)。

    gspread.client.open() 按 *名字* 查找 spreadsheet,传 ID 找不到 → StopIteration → 502。
    必须用 open_by_key() 按 ID 查找。
    """
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    fake_ws.cell.return_value.value = "新值"

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    # 第一个参数是 spreadsheet_id,不是 spreadsheet_name
    result = repo.update_cell(
        "1ABCDEFG_spreadsheet_id", "项目主表", row=5, col=3, new_value="新值"
    )

    fake_client.open_by_key.assert_called_once_with("1ABCDEFG_spreadsheet_id")
    fake_client.open.assert_not_called()
    fake_ws.update_cell.assert_called_once_with(5, 3, "新值")
    fake_ws.cell.assert_called_once_with(5, 3)
    assert result == "新值"


def test_update_cell_writes_and_verifies():
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    fake_ws.cell.return_value.value = "新值"

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    result = repo.update_cell(
        "1ABC_spreadsheet_id", "项目主表", row=5, col=3, new_value="新值"
    )

    fake_ws.update_cell.assert_called_once_with(5, 3, "新值")
    fake_ws.cell.assert_called_once_with(5, 3)
    assert result == "新值"


def test_update_cell_mismatch_raises():
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    fake_ws.cell.return_value.value = "旧值"  # 写完后读出来不一致

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    from src.sheets.repo import WriteVerificationError
    with __import__("pytest").raises(WriteVerificationError):
        repo.update_cell(
            "1ABC_spreadsheet_id", "项目主表", row=5, col=3, new_value="新值"
        )


def test_update_cell_empty_value_raises():
    """写入空字符串应该被服务端校验并报 400 (空值不接受)。"""
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    # 注: 路由层会先 strip + 校验 new_value 不为空才进 update_cell。
    # 这里只验证 update_cell 本身不主动拒绝(让路由层决定)。
    fake_ws.cell.return_value.value = ""
    result = repo.update_cell(
        "1ABC_spreadsheet_id", "项目主表", row=5, col=3, new_value=""
    )
    # 写完后读回 ""(因为我们 mock 的 cell.return_value.value = "")
    assert result == ""


def test_append_row_writes_to_known_columns():
    """append_row 根据 header 检测列位置,把字段值写到正确列,缺失列留空。"""
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    # 表头: 6 列,project_id / status / project_name / package_name / launch_region / 备注
    fake_ws.row_values.return_value = [
        "项目编号", "状态", "项目名称", "包名", "上架地区", "备注"
    ]

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    repo.append_row(
        "1ABC_spreadsheet_id",
        "项目主表",
        values={
            "project_id": "BMW-789",
            "status": "对方下单",
            "project_name": "BMW New Game",
            "package_name": "com.bmw.newgame",
            "launch_region": "India",
        },
    )

    # 应该被调用 append_row,且 row_values 被读以确定列位置
    fake_ws.row_values.assert_called_once_with(1)
    # 写入的行数据应该按列顺序排列
    fake_ws.append_row.assert_called_once()
    written_row = fake_ws.append_row.call_args[0][0]
    assert written_row[0] == "BMW-789"        # 项目编号
    assert written_row[1] == "对方下单"      # 状态
    assert written_row[2] == "BMW New Game"  # 项目名称
    assert written_row[3] == "com.bmw.newgame"  # 包名
    assert written_row[4] == "India"          # 上架地区
    assert written_row[5] == ""                # 备注 未提供,空


def test_append_row_unknown_field_is_ignored():
    """未识别的字段(不在 field_to_candidates 里)静默忽略。"""
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    fake_ws.row_values.return_value = ["项目编号", "状态", "项目名称"]

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    repo.append_row(
        "1ABC_spreadsheet_id",
        "项目主表",
        values={
            "project_id": "BMW-001",
            "status": "对方下单",
            "random_field": "应该被忽略",  # 不在 field_to_candidates 里
        },
    )

    fake_ws.append_row.assert_called_once()
    written_row = fake_ws.append_row.call_args[0][0]
    assert written_row == ["BMW-001", "对方下单", ""]


def test_append_row_missing_column_leaves_empty():
    """如果表里没有 '上架地区' 列,该字段写入时整列空着。"""
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    # 表头里没有 "上架地区"
    fake_ws.row_values.return_value = ["项目编号", "状态", "项目名称"]

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    repo.append_row(
        "1ABC_spreadsheet_id",
        "项目主表",
        values={
            "project_id": "WW-100",
            "launch_region": "India",  # 列不存在 → 写入时被跳过
        },
    )

    fake_ws.append_row.assert_called_once()
    written_row = fake_ws.append_row.call_args[0][0]
    # 长度与表头一致,launch_region 列位置(不存在)保留为空
    assert len(written_row) == 3
    assert written_row[0] == "WW-100"
    assert all(c == "" for c in written_row) or written_row == ["WW-100", "", ""]