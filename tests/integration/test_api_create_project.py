"""Tests for POST /api/projects + GET /api/groups (新增项目 feature)。"""
from unittest.mock import MagicMock


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