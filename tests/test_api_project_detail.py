from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.models.project import Field, Project, SheetView
from src.models.status import StatusCode
from src.web.app import create_app
from src.web.cache import ProjectCache


def _app():
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    app = create_app(cfg, MagicMock(), MagicMock(), MagicMock(), bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    return TestClient(app), cache


def test_api_project_detail_200_payload_shape():
    client, cache = _app()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[SheetView(
            spreadsheet_id="ss1",
            sheet_name="项目主表",
            fields=[
                Field(name="项目编号", value="PRJ-001", column_index=1, row_index=2, recognized_as="project_id"),
                Field(name="备注", value="OK", column_index=5, row_index=2, recognized_as=None),
            ],
            fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )],
    )
    cache.replace([p])
    r = client.get("/api/projects/PRJ-001")
    assert r.status_code == 200
    body = r.json()
    assert body["project"]["project_id"] == "PRJ-001"
    sheet = body["project"]["sheets"][0]
    assert sheet["spreadsheet_name"] == "项目主表"
    field = sheet["fields"][0]
    assert field["field_id"] == "ss1::项目主表::2::1"  # spreadsheet_id::sheet_name::row::col
    assert field["editable"] is False  # project_id locked
    field2 = sheet["fields"][1]
    assert field2["editable"] is True


def test_api_project_detail_404():
    client, cache = _app()
    cache.replace([])
    r = client.get("/api/projects/PRJ-NOPE")
    assert r.status_code == 404

def test_field_id_uses_spreadsheet_id_not_sheet_name():
    """field_id 的第一段必须是 spreadsheet_id(长 alphanumeric),不是 sheet_name(中文)。

    之前 field_payload / 模板都把 sheet_name 当 spreadsheet_id 用,
    导致 gspread open_by_key 拿到 sheet_name,API 返回 404。
    """
    from datetime import datetime, timezone
    from src.models.project import Field, Project, SheetView
    from src.models.status import StatusCode

    p = Project(
        project_id="TEST-001",
        project_name="测试",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        sheets=[
            SheetView(
                spreadsheet_id="1REAL_SPREADSHEET_ID_ABC",
                sheet_name="工作表1",
                fields=[
                    Field(name="状态", value="我方制作中", column_index=1, row_index=2, recognized_as="status"),
                    Field(name="包名", value="com.test", column_index=2, row_index=2),
                ],
                fetched_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
            ),
        ],
    )

    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    from src.web.app import create_app
    from src.web.cache import ProjectCache

    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = []
    store = MagicMock()
    sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    cache = ProjectCache()
    cache.replace([p])
    app.state.cache = cache
    client = TestClient(app)

    r = client.get("/api/projects/TEST-001")
    assert r.status_code == 200
    fields = r.json()["project"]["sheets"][0]["fields"]
    # field_id 必须以 spreadsheet_id 开头,不是 sheet_name
    for f in fields:
        fid = f["field_id"]
        assert fid.startswith("1REAL_SPREADSHEET_ID_ABC::"), (
            f"field_id 第一段应该是 spreadsheet_id,实际是 {fid!r}"
        )
        # 不应该以中文 sheet_name 开头
        assert not fid.startswith("工作表1::"), (
            f"field_id 不应该以 sheet_name 开头,实际是 {fid!r}"
        )
