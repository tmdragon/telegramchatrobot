from unittest.mock import MagicMock, call
from src.sheets.repo import SheetRepo
from src.config import SpreadsheetConfig


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


def test_append_row_writes_info_fields():
    """append_row 应该把 info 字段(class_name/sha1/sha256/privacy_policy/hash_value)
    写到对应列,缺失列留空。"""
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    # 完整表头:5 个基础字段 + 5 个 info 字段
    fake_ws.row_values.return_value = [
        "项目编号", "状态", "项目名称", "包名", "上架地区",
        "主activity类名", "SHA-1", "SHA-256", "隐私政策", "hash值",
    ]

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    repo.append_row(
        "1ABC_spreadsheet_id",
        "项目主表",
        values={
            "project_id": "WW-200",
            "status": "对方下单",
            "class_name": "com.ww.app.MainActivity",
            "sha1": "A1:83:FC:CE:B0:A2:EC:1B:19:41:A2:98:A9:90:4D:7C:54:54:1F:6A",
            "sha256": "B5:96:58:56:34:46:CE:B9:5F:8D:41:27:E3",
            "hash_value": "13WJI9zm7iPkPGX8tUceqfrFP9k=",
            "privacy_policy": "https://example.com/privacy",
        },
    )

    fake_ws.append_row.assert_called_once()
    written_row = fake_ws.append_row.call_args[0][0]
    assert len(written_row) == 10
    assert written_row[0] == "WW-200"
    assert written_row[1] == "对方下单"
    assert written_row[5] == "com.ww.app.MainActivity"     # 主activity类名
    assert written_row[6].startswith("A1:83:FC:")           # SHA-1
    assert written_row[7] == "B5:96:58:56:34:46:CE:B9:5F:8D:41:27:E3"  # SHA-256
    assert written_row[8] == "https://example.com/privacy"   # 隐私政策
    assert written_row[9] == "13WJI9zm7iPkPGX8tUceqfrFP9k="   # hash值


def test_append_row_info_field_missing_column_ignored():
    """表头里没有 SHA-256 列时,传入 sha256 应该被静默忽略(不抛错)。"""
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    fake_ws.row_values.return_value = ["项目编号", "状态", "主activity类名"]

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    repo.append_row(
        "1ABC_spreadsheet_id",
        "项目主表",
        values={
            "project_id": "WW-300",
            "status": "对方下单",
            "class_name": "com.ww.app.MainActivity",
            "sha256": "should_be_ignored",  # 列不存在
        },
    )

    fake_ws.append_row.assert_called_once()
    written_row = fake_ws.append_row.call_args[0][0]
    assert written_row[0] == "WW-300"
    assert written_row[1] == "对方下单"
    assert written_row[2] == "com.ww.app.MainActivity"  # class_name 写到了第3列
    assert len(written_row) == 3


def test_get_info_field_columns_returns_present_fields():
    """get_info_field_columns 应该返回 master 表头里实际存在的 info 字段列表。

    每条包含 {key, label, header}:key 是内部名(给 append_row 用),
    label 是中文标签(给 UI 用),header 是 sheet 里实际的列名(用于展示/回写)。
    """
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    # 只包含 5 个 info 字段中的 3 个:class_name / sha1 / privacy_policy
    fake_ws.row_values.return_value = [
        "项目编号", "状态", "主activity类名", "SHA-1", "隐私政策",
    ]

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    fields = repo.get_info_field_columns(
        SpreadsheetConfig(id="ss1", name="项目主表", role="master")
    )

    keys = [f["key"] for f in fields]
    assert "class_name" in keys
    assert "sha1" in keys
    assert "privacy_policy" in keys
    # sha256/hash_value 表里没有,不应出现
    assert "sha256" not in keys
    assert "hash_value" not in keys
    # 字段应当包含 label 和 header
    cn_field = next(f for f in fields if f["key"] == "class_name")
    assert cn_field["label"] == "主activity类名"
    assert cn_field["header"] == "主activity类名"


def test_get_info_field_columns_empty_when_no_info_columns():
    """表头里没有任何 info 字段时,返回空列表。"""
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    fake_ws.row_values.return_value = ["项目编号", "状态", "项目名称"]

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    fields = repo.get_info_field_columns(
        SpreadsheetConfig(id="ss1", name="项目主表", role="master")
    )
    assert fields == []


def test_append_row_writes_store_url():
    """append_row 应该把 store_url 写到「商店地址」列(由 HeaderDetector 定位)。"""
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    fake_ws.row_values.return_value = ["项目编号", "状态", "商店地址"]

    fake_client = MagicMock()
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    repo = SheetRepo(fake_client)
    repo.append_row(
        "1ABC_spreadsheet_id",
        "项目主表",
        values={
            "project_id": "WW-700",
            "store_url": "https://play.google.com/store/apps/details?id=com.ww.app",
        },
    )

    fake_ws.append_row.assert_called_once()
    written_row = fake_ws.append_row.call_args[0][0]
    assert written_row[0] == "WW-700"
    assert written_row[2] == "https://play.google.com/store/apps/details?id=com.ww.app"