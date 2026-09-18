from unittest.mock import MagicMock, call
from src.sheets.repo import SheetRepo


def test_update_cell_writes_and_verifies():
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    fake_ws.cell.return_value.value = "新值"

    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    result = repo.update_cell("项目主表", "项目主表", row=5, col=3, new_value="新值")

    fake_ws.update_cell.assert_called_once_with(5, 3, "新值")
    fake_ws.cell.assert_called_once_with(5, 3)
    assert result == "新值"


def test_update_cell_mismatch_raises():
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    fake_ws.cell.return_value.value = "旧值"  # 写完后读出来不一致

    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    from src.sheets.repo import WriteVerificationError
    with __import__("pytest").raises(WriteVerificationError):
        repo.update_cell("项目主表", "项目主表", row=5, col=3, new_value="新值")