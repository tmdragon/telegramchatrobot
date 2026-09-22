"""Tests for /info bot command (查项目投放信息)。"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.project import Field, Project, SheetView


def _make_project(pid: str, fields_dict: dict) -> Project:
    """构造带指定 fields 的 Project。fields_dict key 是 recognized_as。"""
    fields = [
        Field(name=k, value=v, column_index=i + 1, row_index=2, recognized_as=k)
        for i, (k, v) in enumerate(fields_dict.items())
        if v is not None
    ]
    return Project(
        project_id=pid,
        project_name=fields_dict.get("project_name"),
        package_name=fields_dict.get("package_name"),
        status=fields_dict.get("status"),
        sheets=[SheetView(
            spreadsheet_id="ss1",
            sheet_name="项目主表",
            fields=fields,
            fetched_at=datetime.now(timezone.utc),
        )],
    )


def _make_update(text: str) -> MagicMock:
    update = MagicMock()
    update.effective_chat = MagicMock(id=-100111222333)
    update.message = MagicMock()
    update.message.text = text
    return update


def _make_context(cache: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.args = []
    ctx.bot_data = {
        "cache": cache,
        "admin_chat_id": 0,
        "admin_broadcast_chats": [],
    }
    return ctx


@pytest.mark.asyncio
async def test_info_full_match_all_fields_present():
    """精确 project_id 匹配,且所有字段都有 → 返回完整信息块。"""
    from src.bot.commands import info_cmd

    p = _make_project("WW-001", {
        "project_id": "WW-001",
        "package_name": "com.gggame.towerup.game1",
        "class_name": "com.gggame.towerup.game1.MainActivity",
        "sha1": "A1:83:FC:CE:B0:...",
        "sha256": "B5:96:58:56:34:46...",
        "hash_value": "13WJI9zm7iPkPGX8...",
        "privacy_policy": "https://www.freeprivacypolicy.com/...",
        "store_url": "https://play.google.com/store/apps/details?id=com.gggame.towerup.game1",
    })

    cache = MagicMock()
    cache.get.return_value = p
    cache.list_projects.return_value = [p]

    update = _make_update("/info WW-001")
    ctx = _make_context(cache)
    ctx.args = ["WW-001"]

    with patch("src.bot.commands._reply", new=AsyncMock()) as mock_reply:
        await info_cmd(update, ctx)

    mock_reply.assert_called_once()
    text = mock_reply.call_args[0][1]
    # 所有字段都在
    assert "WW-001" in text
    assert "com.gggame.towerup.game1" in text
    assert "com.gggame.towerup.game1.MainActivity" in text
    assert "A1:83:FC:CE:B0:" in text
    assert "B5:96:58:56:34:46" in text
    assert "13WJI9zm7iPkPGX8" in text
    assert "freeprivacypolicy.com" in text
    assert "play.google.com" in text


@pytest.mark.asyncio
async def test_info_missing_fields_returns_error():
    """精确匹配但字段缺失 → 返回"提取失败,缺失 XXX"消息。"""
    from src.bot.commands import info_cmd

    # 缺 sha1 和 hash_value(其他都有)
    p = _make_project("WW-002", {
        "package_name": "com.example.app",
        "class_name": "com.example.app.MainActivity",
        "sha256": "AB:CD:",
        "privacy_policy": "https://example.com/privacy",
        "store_url": "https://example.com/app",
    })

    cache = MagicMock()
    cache.get.return_value = p
    cache.list_projects.return_value = [p]

    update = _make_update("/info WW-002")
    ctx = _make_context(cache)
    ctx.args = ["WW-002"]

    with patch("src.bot.commands._reply", new=AsyncMock()) as mock_reply:
        await info_cmd(update, ctx)

    text = mock_reply.call_args[0][1]
    # 错误格式
    assert "WW-002" in text
    assert "提取失败" in text
    assert "请补充" in text
    # 列出缺失字段
    assert "SHA-1" in text
    assert "hash值" in text
    # 不列出已有的字段
    assert "包名" not in text or False  # 我们列的是缺失的,不是有的


@pytest.mark.asyncio
async def test_info_no_match_returns_error():
    """无匹配 → 未找到。"""
    from src.bot.commands import info_cmd

    cache = MagicMock()
    cache.get.return_value = None
    cache.list_projects.return_value = []  # 没有匹配

    update = _make_update("/info NOPE-999")
    ctx = _make_context(cache)
    ctx.args = ["NOPE-999"]

    with patch("src.bot.commands._reply", new=AsyncMock()) as mock_reply:
        await info_cmd(update, ctx)

    text = mock_reply.call_args[0][1]
    assert "NOPE-999" in text or "未找到" in text


@pytest.mark.asyncio
async def test_info_multiple_matches_returns_candidates():
    """模糊匹配命中多个 → 列出候选。"""
    from src.bot.commands import info_cmd

    p1 = _make_project("WW-001", {"package_name": "com.ww.app1"})
    p2 = _make_project("WW-002", {"package_name": "com.ww.app2"})

    cache = MagicMock()
    cache.get.return_value = None  # 精确不匹配
    cache.list_projects.return_value = [p1, p2]

    update = _make_update("/info WW")
    ctx = _make_context(cache)
    ctx.args = ["WW"]

    with patch("src.bot.commands._reply", new=AsyncMock()) as mock_reply:
        await info_cmd(update, ctx)

    text = mock_reply.call_args[0][1]
    # 列出两个候选
    assert "WW-001" in text
    assert "WW-002" in text
    assert "多个" in text or "请用编号" in text


@pytest.mark.asyncio
async def test_info_lookup_by_package_name_fuzzy():
    """模糊匹配按 package_name。"""
    from src.bot.commands import info_cmd

    p = _make_project("WW-007", {
        "project_id": "WW-007",
        "package_name": "com.bmw.neuesSpiel",
        "class_name": "com.bmw.neuesSpiel.MainActivity",
        "sha1": "AB",
        "sha256": "CD",
        "hash_value": "EF",
        "privacy_policy": "https://bmw.com/p",
        "store_url": "https://bmw.com/a",
    })

    cache = MagicMock()
    cache.get.return_value = None  # 精确不匹配
    cache.list_projects.return_value = [p]

    update = _make_update("/info neuesSpiel")
    ctx = _make_context(cache)
    ctx.args = ["neuesSpiel"]

    with patch("src.bot.commands._reply", new=AsyncMock()) as mock_reply:
        await info_cmd(update, ctx)

    text = mock_reply.call_args[0][1]
    assert "WW-007" in text
    assert "com.bmw.neuesSpiel" in text


@pytest.mark.asyncio
async def test_info_no_args_shows_usage():
    """不带参数 → 显示用法。"""
    from src.bot.commands import info_cmd

    update = _make_update("/info")
    ctx = _make_context(MagicMock())
    ctx.args = []

    with patch("src.bot.commands._reply", new=AsyncMock()) as mock_reply:
        await info_cmd(update, ctx)

    text = mock_reply.call_args[0][1]
    assert "/info" in text or "用法" in text