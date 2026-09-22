"""Tests for POST /api/projects + GET /api/groups (新增项目 feature)。"""
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.cache import ProjectCache


def _make_app(spreadsheets=None, sheet_repo=None):
    cfg = MagicMock()
    cfg.ui_bind = "127.0.0.1"
    cfg.ui_port = 8765
    cfg.spreadsheets = spreadsheets if spreadsheets is not None else [
        MagicMock(id="ss1", name="项目主表", role="master"),
    ]
    store = MagicMock()
    if sheet_repo is None:
        sheet_repo = MagicMock()
    mapping_repo = MagicMock()
    app = create_app(cfg, store, sheet_repo, mapping_repo, bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    return TestClient(app), app, cache, sheet_repo


def test_get_groups_dedups_by_chat_id():
    """GET /api/groups 从 mapping sheet 提取去重的 (chat_id, 备注) 列表。"""
    fake_ws = MagicMock()
    fake_ws.get_all_values.return_value = [
        ["项目编号", "群 chat_id", "备注", "是否启用", "上次播报时间"],
        ["PRJ-001", "-100111", "BMW 客户", "TRUE", ""],
        ["PRJ-002", "-100222", "Audi 客户", "TRUE", ""],
        ["PRJ-003", "-100111", "BMW 客户", "TRUE", ""],  # 重复 chat_id
        ["PRJ-004", "-100333", "Tesla 客户", "FALSE", ""],  # disabled
    ]

    fake_client = MagicMock()
    fake_client.open.return_value.worksheet.return_value = fake_ws

    from src.sheets.mapping_repo import MappingRepo

    repo = MappingRepo(fake_client, spreadsheet_name="项目群映射")
    mappings = repo.load_all()

    # load_all 不去重(它返回每行一个 Mapping),但我们后面会在路由层去重
    # 这里只验证 load_all 正确读取
    assert len(mappings) == 4
    chat_ids = [m.chat_id for m in mappings]
    assert "-100111" in chat_ids
    assert "-100333" in chat_ids


def test_unique_groups_dedup():
    """路由层的 _unique_groups 应该按 chat_id 去重,保留每条 chat_id 的 备注。"""
    from src.web.routes.api import _unique_groups
    from src.models.project import Mapping

    mappings = [
        Mapping(project_id="A", chat_id="-100111", note="BMW 客户", enabled=True),
        Mapping(project_id="B", chat_id="-100222", note="Audi 客户", enabled=True),
        Mapping(project_id="C", chat_id="-100111", note="BMW 客户", enabled=True),  # 重复
        Mapping(project_id="D", chat_id="-100333", note="Tesla 客户", enabled=True),
    ]
    groups = _unique_groups(mappings)
    # 按 chat_id 去重,保留 备注
    chat_ids = [g["chat_id"] for g in groups]
    assert len(groups) == 3
    assert "-100111" in chat_ids
    assert "-100222" in chat_ids
    assert "-100333" in chat_ids
    # 备注保留第一次见到的
    assert next(g for g in groups if g["chat_id"] == "-100111")["note"] == "BMW 客户"


def test_unique_groups_disabled_excluded():
    """enabled=False 的 mapping 不应出现在 _unique_groups 结果中(不推荐给新项目用)。"""
    from src.web.routes.api import _unique_groups
    from src.models.project import Mapping

    mappings = [
        Mapping(project_id="A", chat_id="-100111", note="OK", enabled=True),
        Mapping(project_id="B", chat_id="-100222", note="disabled", enabled=False),
    ]
    groups = _unique_groups(mappings)
    chat_ids = [g["chat_id"] for g in groups]
    assert chat_ids == ["-100111"]  # disabled 不应出现


def test_get_new_form_fields_returns_info_fields():
    """GET /api/projects/new-form-fields 应该返回 master 表头里识别到的 info 字段列表。"""
    sheet_repo = MagicMock()
    sheet_repo.get_info_field_columns.return_value = [
        {"key": "class_name", "label": "主activity类名", "header": "主activity类名"},
        {"key": "sha1", "label": "SHA-1", "header": "SHA-1"},
    ]
    client, app, cache, sheet_repo_ = _make_app(sheet_repo=sheet_repo)
    r = client.get("/api/projects/new-form-fields")
    assert r.status_code == 200
    body = r.json()
    assert "info_fields" in body
    keys = [f["key"] for f in body["info_fields"]]
    assert "class_name" in keys
    assert "sha1" in keys
    sheet_repo.get_info_field_columns.assert_called_once()


def test_get_new_form_fields_500_when_no_master():
    """没有配置 master 时,GET 端点返回 500。"""
    client, app, cache, sheet_repo = _make_app(spreadsheets=[])
    r = client.get("/api/projects/new-form-fields")
    assert r.status_code == 500
    assert "master" in r.json()["detail"].lower()


def test_post_project_accepts_info_fields():
    """POST /api/projects 应该把 info 字段透传给 SheetRepo.append_row。"""
    sheet_repo = MagicMock()
    sheet_repo.find_row_by_project_id.return_value = None  # 不冲突
    sheet_repo.fetch_all.return_value = []  # refresh 后空
    cfg_mock = MagicMock()
    cfg_mock.ui_bind = "127.0.0.1"
    cfg_mock.ui_port = 8765
    cfg_mock.spreadsheets = [MagicMock(id="ss1", name="项目主表", role="master")]
    cfg_mock.get = lambda key, default=None: getattr(cfg_mock, key, default)
    store = MagicMock()
    mapping_repo = MagicMock()
    from src.web.app import create_app
    app = create_app(cfg_mock, store, sheet_repo, mapping_repo, bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    client = TestClient(app)

    body = {
        "project_id": "WW-500",
        "project_name": "WW App",
        "package_name": "com.ww.app",
        "launch_region": "India",
        "class_name": "com.ww.app.MainActivity",
        "sha1": "A1:83:FC:CE:B0:A2",
        "sha256": "B5:96:58:56:34:46",
        "privacy_policy": "https://example.com/privacy",
        "hash_value": "abc123",
    }
    r = client.post("/api/projects", json=body)
    assert r.status_code == 200
    # append_row 应该被调用,且 values 里包含所有 info 字段
    sheet_repo.append_row.assert_called_once()
    call_args = sheet_repo.append_row.call_args
    values = call_args[0][2] if len(call_args[0]) >= 3 else call_args.kwargs["values"]
    assert values["class_name"] == "com.ww.app.MainActivity"
    assert values["sha1"] == "A1:83:FC:CE:B0:A2"
    assert values["sha256"] == "B5:96:58:56:34:46"
    assert values["privacy_policy"] == "https://example.com/privacy"
    assert values["hash_value"] == "abc123"


def test_post_project_without_info_fields_still_works():
    """不带 info 字段的旧请求应该仍然能成功(向后兼容)。"""
    sheet_repo = MagicMock()
    sheet_repo.find_row_by_project_id.return_value = None
    sheet_repo.fetch_all.return_value = []
    cfg_mock = MagicMock()
    cfg_mock.ui_bind = "127.0.0.1"
    cfg_mock.ui_port = 8765
    cfg_mock.spreadsheets = [MagicMock(id="ss1", name="项目主表", role="master")]
    store = MagicMock()
    mapping_repo = MagicMock()
    from src.web.app import create_app
    app = create_app(cfg_mock, store, sheet_repo, mapping_repo, bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    client = TestClient(app)

    body = {"project_id": "WW-600", "project_name": "WW App"}
    r = client.post("/api/projects", json=body)
    assert r.status_code == 200
    sheet_repo.append_row.assert_called_once()
    call_args = sheet_repo.append_row.call_args
    values = call_args[0][2] if len(call_args[0]) >= 3 else call_args.kwargs["values"]
    # 不带 info 字段时,应该全部为空字符串(由 NewProjectBody 默认值提供)
    assert values.get("class_name", "") == ""
    assert values.get("sha1", "") == ""
    assert values.get("sha256", "") == ""
    assert values.get("privacy_policy", "") == ""
    assert values.get("hash_value", "") == ""


def test_post_project_accepts_store_url():
    """POST /api/projects 应该接受 store_url(GP checkbox 默认填充的 URL)。"""
    sheet_repo = MagicMock()
    sheet_repo.find_row_by_project_id.return_value = None
    sheet_repo.fetch_all.return_value = []
    cfg_mock = MagicMock()
    cfg_mock.ui_bind = "127.0.0.1"
    cfg_mock.ui_port = 8765
    cfg_mock.spreadsheets = [MagicMock(id="ss1", name="项目主表", role="master")]
    store = MagicMock()
    mapping_repo = MagicMock()
    from src.web.app import create_app
    app = create_app(cfg_mock, store, sheet_repo, mapping_repo, bot_service=None)
    cache = ProjectCache()
    app.state.cache = cache
    client = TestClient(app)

    body = {
        "project_id": "WW-800",
        "project_name": "WW App",
        "package_name": "com.ww.app",
        "store_url": "https://play.google.com/store/apps/details?id=com.ww.app",
    }
    r = client.post("/api/projects", json=body)
    assert r.status_code == 200
    sheet_repo.append_row.assert_called_once()
    call_args = sheet_repo.append_row.call_args
    values = call_args[0][2] if len(call_args[0]) >= 3 else call_args.kwargs["values"]
    assert values["store_url"] == "https://play.google.com/store/apps/details?id=com.ww.app"