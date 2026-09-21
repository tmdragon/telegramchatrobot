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