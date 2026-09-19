"""bot 命令处理器测试。用 MagicMock 模拟 Update/Context。"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.commands import (
    help_cmd,
    projects_cmd,
    status_cmd,
    force_broadcast_cmd,
    reload_cmd,
    dryrun_cmd,
    register_handlers,
    _is_admin,
)
from src.models.project import Mapping, Project
from src.models.status import StatusCode
from src.web.cache import ProjectCache


pytestmark = pytest.mark.asyncio


ADMIN_ID = 111


def _make_update(*, user_id: int, chat_id: int = 999, text: str | None = None, args: list[str] | None = None):
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.text = text or "/help"
    return update


def _make_context(args: list[str] | None = None):
    ctx = MagicMock()
    ctx.args = args or []
    return ctx


# ---------- _is_admin ----------

def test_is_admin_true_when_match():
    u = _make_update(user_id=ADMIN_ID)
    assert _is_admin(u, ADMIN_ID) is True


def test_is_admin_false_when_mismatch():
    u = _make_update(user_id=42)
    assert _is_admin(u, ADMIN_ID) is False


# ---------- /help ----------

async def test_help_cmd_replies_with_command_list():
    u = _make_update(user_id=42)
    c = _make_context()
    await help_cmd(u, c)
    u.message.reply_text.assert_awaited_once()
    text = u.message.reply_text.await_args.args[0]
    assert "/status" in text
    assert "/projects" in text
    assert "/help" in text
    assert "/force_broadcast" in text  # wrapped in backticks (no MarkdownV2 escaping needed)
    assert "/reload" in text
    assert "/dryrun" in text


# ---------- /status ----------

async def test_status_cmd_with_known_project():
    cache = ProjectCache()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        package_name="com.example.game1",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[],
    )
    cache.replace([p])
    # admin 私聊：可看任意项目
    u = _make_update(user_id=ADMIN_ID, chat_id=ADMIN_ID, args=["PRJ-001"])
    c = _make_context(args=["PRJ-001"])
    c.bot_data = {"cache": cache, "admin_chat_id": ADMIN_ID,
                  "admin_broadcast_chats": []}
    await status_cmd(u, c)
    u.message.reply_text.assert_awaited_once()
    text = u.message.reply_text.await_args.args[0]
    assert "PRJ-001" in text
    assert "MAKING" in text or "我方制作中" in text
    assert "com.example.game1" in text


async def test_status_cmd_search_by_package_name():
    cache = ProjectCache()
    cache.replace([
        Project(project_id="PRJ-001", project_name="项目一",
                package_name="com.example.game1",
                status=StatusCode.MAKING, status_changed_at=None, sheets=[]),
        Project(project_id="PRJ-002", project_name="项目二",
                package_name="com.other.pkg",
                status=StatusCode.PUBLISHED, status_changed_at=None, sheets=[]),
    ])
    u = _make_update(user_id=ADMIN_ID, chat_id=ADMIN_ID, args=["com.example.game1"])
    c = _make_context(args=["com.example.game1"])
    c.bot_data = {"cache": cache, "admin_chat_id": ADMIN_ID,
                  "admin_broadcast_chats": []}
    await status_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "PRJ-001" in text
    assert "com.example.game1" in text


async def test_status_cmd_search_by_project_name():
    cache = ProjectCache()
    cache.replace([
        Project(project_id="PRJ-001", project_name="Tower up up",
                package_name="com.tower.game",
                status=StatusCode.PUBLISHED, status_changed_at=None, sheets=[]),
        Project(project_id="PRJ-002", project_name="Other Game",
                status=StatusCode.MAKING, status_changed_at=None, sheets=[]),
    ])
    u = _make_update(user_id=ADMIN_ID, chat_id=ADMIN_ID, args=["Tower"])
    c = _make_context(args=["Tower"])
    c.bot_data = {"cache": cache, "admin_chat_id": ADMIN_ID,
                  "admin_broadcast_chats": []}
    await status_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "PRJ-001" in text
    assert "Tower up up" in text


async def test_status_cmd_multiple_matches_returns_disambiguation():
    cache = ProjectCache()
    cache.replace([
        Project(project_id="PRJ-001", project_name="Tower up",
                package_name="com.tower.game1", status=StatusCode.PUBLISHED,
                status_changed_at=None, sheets=[]),
        Project(project_id="PRJ-002", project_name="Tower down",
                package_name="com.tower.game2", status=StatusCode.MAKING,
                status_changed_at=None, sheets=[]),
    ])
    u = _make_update(user_id=ADMIN_ID, chat_id=ADMIN_ID, args=["tower"])
    c = _make_context(args=["tower"])
    c.bot_data = {"cache": cache, "admin_chat_id": ADMIN_ID,
                  "admin_broadcast_chats": []}
    await status_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "PRJ-001" in text
    assert "PRJ-002" in text
    assert "多个匹配" in text or "tower" in text.lower()


async def test_status_cmd_with_unknown_project():
    cache = ProjectCache()
    cache.replace([])
    u = _make_update(user_id=ADMIN_ID, chat_id=ADMIN_ID, args=["PRJ-NOPE"])
    c = _make_context(args=["PRJ-NOPE"])
    c.bot_data = {"cache": cache, "admin_chat_id": ADMIN_ID,
                  "admin_broadcast_chats": []}
    await status_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "未找到" in text or "not found" in text.lower()


async def test_status_cmd_without_args_prompts():
    cache = ProjectCache()
    u = _make_update(user_id=ADMIN_ID, chat_id=ADMIN_ID, args=[])
    c = _make_context(args=[])
    c.bot_data = {"cache": cache, "admin_chat_id": ADMIN_ID,
                  "admin_broadcast_chats": []}
    await status_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "/status" in text or "项目编号" in text


async def test_status_cmd_customer_rejects_unmapped_project():
    """客户群查未映射的项目 → 拒绝（🔒）"""
    cache = ProjectCache()
    p = Project(
        project_id="WW-001", project_name="项目WW",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[],
    )
    cache.replace([p])
    mapping_repo = MagicMock()
    mapping_repo.load_all = MagicMock(return_value=[
        Mapping(project_id="PAK-001", chat_id="-100123", note="",
                enabled=True, last_broadcast_at=None,
                last_broadcast_status=None, last_error=None),
    ])
    u = _make_update(user_id=42, chat_id=-100123, args=["WW-001"])
    c = _make_context(args=["WW-001"])
    c.bot_data = {
        "cache": cache, "mapping_repo": mapping_repo,
        "admin_chat_id": ADMIN_ID,
        "admin_broadcast_chats": [],
    }
    await status_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "🔒" in text or "本群" in text
    # 不应泄漏 WW-001 的 status
    assert "MAKING" not in text


async def test_status_cmd_customer_allows_mapped_project():
    """客户群查本群映射的项目 → 正常返回"""
    cache = ProjectCache()
    p = Project(
        project_id="PAK-001", project_name="项目PAK",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[],
    )
    cache.replace([p])
    mapping_repo = MagicMock()
    mapping_repo.load_all = MagicMock(return_value=[
        Mapping(project_id="PAK-001", chat_id="-100123", note="",
                enabled=True, last_broadcast_at=None,
                last_broadcast_status=None, last_error=None),
    ])
    u = _make_update(user_id=42, chat_id=-100123, args=["PAK-001"])
    c = _make_context(args=["PAK-001"])
    c.bot_data = {
        "cache": cache, "mapping_repo": mapping_repo,
        "admin_chat_id": ADMIN_ID,
        "admin_broadcast_chats": [],
    }
    await status_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "PAK-001" in text
    assert "MAKING" in text or "我方制作中" in text


# ---------- /projects ----------

async def test_projects_cmd_admin_sees_all():
    """admin 私聊 /projects 看所有项目"""
    cache = ProjectCache()
    p1 = Project(project_id="PRJ-001", project_name="项目一",
                 status=StatusCode.MAKING, status_changed_at=None, sheets=[])
    p2 = Project(project_id="PRJ-002", project_name=None,
                 status=StatusCode.PUBLISHED, status_changed_at=None, sheets=[])
    cache.replace([p1, p2])
    u = _make_update(user_id=ADMIN_ID, chat_id=ADMIN_ID)
    c = _make_context()
    c.bot_data = {"cache": cache, "admin_chat_id": ADMIN_ID,
                  "admin_broadcast_chats": []}
    await projects_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "PRJ-001" in text
    assert "PRJ-002" in text


async def test_projects_cmd_admin_broadcast_chat_sees_all():
    """内部管理群（admin_broadcast_chats）也看所有项目"""
    cache = ProjectCache()
    p1 = Project(project_id="PRJ-001", project_name="项目一",
                 status=StatusCode.MAKING, status_changed_at=None, sheets=[])
    p2 = Project(project_id="PRJ-002", project_name=None,
                 status=StatusCode.PUBLISHED, status_changed_at=None, sheets=[])
    cache.replace([p1, p2])
    internal_chat_id = -200
    u = _make_update(user_id=42, chat_id=internal_chat_id)
    c = _make_context()
    c.bot_data = {"cache": cache, "admin_chat_id": ADMIN_ID,
                  "admin_broadcast_chats": [str(internal_chat_id)]}
    await projects_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "PRJ-001" in text
    assert "PRJ-002" in text


async def test_projects_cmd_customer_sees_only_mapped():
    """客户群 /projects 只显示本群映射的项目"""
    cache = ProjectCache()
    p1 = Project(project_id="PAK-001", project_name="项目一",
                 status=StatusCode.MAKING, status_changed_at=None, sheets=[])
    p2 = Project(project_id="WW-001", project_name="WW",
                 status=StatusCode.MAKING, status_changed_at=None, sheets=[])
    p3 = Project(project_id="PAK-002", project_name=None,
                 status=StatusCode.PUBLISHED, status_changed_at=None, sheets=[])
    cache.replace([p1, p2, p3])
    mapping_repo = MagicMock()
    mapping_repo.load_all = MagicMock(return_value=[
        Mapping(project_id="PAK-001", chat_id="-100123", note="",
                enabled=True, last_broadcast_at=None,
                last_broadcast_status=None, last_error=None),
        Mapping(project_id="PAK-002", chat_id="-100123", note="",
                enabled=True, last_broadcast_at=None,
                last_broadcast_status=None, last_error=None),
    ])
    u = _make_update(user_id=42, chat_id=-100123)
    c = _make_context()
    c.bot_data = {
        "cache": cache, "mapping_repo": mapping_repo,
        "admin_chat_id": ADMIN_ID,
        "admin_broadcast_chats": [],
    }
    await projects_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "PAK-001" in text
    assert "PAK-002" in text
    # 关键断言：WW-001 不应出现
    assert "WW-001" not in text


async def test_projects_cmd_customer_no_mappings_returns_empty():
    """客户群无映射 → 显示空提示"""
    cache = ProjectCache()
    p1 = Project(project_id="PAK-001", project_name="项目一",
                 status=StatusCode.MAKING, status_changed_at=None, sheets=[])
    cache.replace([p1])
    mapping_repo = MagicMock()
    mapping_repo.load_all = MagicMock(return_value=[])
    u = _make_update(user_id=42, chat_id=-100123)
    c = _make_context()
    c.bot_data = {
        "cache": cache, "mapping_repo": mapping_repo,
        "admin_chat_id": ADMIN_ID,
        "admin_broadcast_chats": [],
    }
    await projects_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "PAK-001" not in text


async def test_projects_cmd_includes_package_name():
    """ProjectSummary.package_name 应出现在 /projects 输出中。"""
    cache = ProjectCache()
    # 直接塞进 ProjectCache（绕过 list_summaries）
    cache._projects["PAK-001"] = Project(
        project_id="PAK-001", project_name="项目一",
        package_name="com.example.pkg1",
        status=StatusCode.MAKING, status_changed_at=None, sheets=[],
    )
    mapping_repo = MagicMock()
    mapping_repo.load_all = MagicMock(return_value=[
        Mapping(project_id="PAK-001", chat_id="-100123", note="",
                enabled=True, last_broadcast_at=None,
                last_broadcast_status=None, last_error=None),
    ])
    u = _make_update(user_id=42, chat_id=-100123)
    c = _make_context()
    c.bot_data = {
        "cache": cache, "mapping_repo": mapping_repo,
        "admin_chat_id": ADMIN_ID,
        "admin_broadcast_chats": [],
    }
    await projects_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "PAK-001" in text
    assert "com.example.pkg1" in text


# ---------- admin gates ----------

async def test_force_broadcast_rejects_non_admin():
    u = _make_update(user_id=42)
    c = _make_context()
    c.bot_data = {"admin_chat_id": ADMIN_ID, "broadcast_svc": MagicMock(broadcast_all=AsyncMock())}
    await force_broadcast_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "管理员" in text or "⛔" in text


async def test_force_broadcast_runs_for_admin():
    svc = MagicMock()
    svc.broadcast_all = AsyncMock(return_value={"sent": 1, "skipped": 0, "failed": 0})
    u = _make_update(user_id=ADMIN_ID)
    c = _make_context()
    c.bot_data = {"admin_chat_id": ADMIN_ID, "broadcast_svc": svc}
    await force_broadcast_cmd(u, c)
    svc.broadcast_all.assert_awaited_once()
    text = u.message.reply_text.await_args.args[0]
    assert "完成" in text or "✅" in text


async def test_reload_rejects_non_admin():
    u = _make_update(user_id=42)
    c = _make_context()
    c.bot_data = {"admin_chat_id": ADMIN_ID, "store": MagicMock(),
                  "mapping_repo": MagicMock(), "cache": ProjectCache()}
    await reload_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "管理员" in text or "⛔" in text


async def test_dryrun_returns_rendered_text_without_sending():
    svc = MagicMock()
    svc.broadcast_all = AsyncMock(return_value={
        "sent": 0, "skipped": 0, "failed": 0, "dryrun": True, "preview": "📊 PRJ-001"
    })
    u = _make_update(user_id=ADMIN_ID)
    c = _make_context()
    c.bot_data = {"admin_chat_id": ADMIN_ID, "broadcast_svc": svc}
    await dryrun_cmd(u, c)
    svc.broadcast_all.assert_awaited_once()
    call = svc.broadcast_all.await_args
    assert call.kwargs.get("dryrun") is True


# ---------- register_handlers ----------

async def test_register_handlers_registers_six():
    app = MagicMock()
    app.add_handler = MagicMock()
    app.bot_data = {}  # 用真 dict 便于断言
    cache = ProjectCache()
    register_handlers(
        app, admin_chat_id=ADMIN_ID, admin_broadcast_chats=[],
        cache=cache,
        broadcast_svc=MagicMock(), bot_service=MagicMock(), store=MagicMock(),
    )
    # 6 CommandHandler + 1 监听 user_id 的 MessageHandler（hint）= 至少 6 次
    assert app.add_handler.call_count >= 6
    # 关键键值都注入到 bot_data
    assert app.bot_data["admin_chat_id"] == ADMIN_ID
    assert app.bot_data["admin_broadcast_chats"] == []


# ---------- /chatid ----------

async def test_chatid_cmd_replies_with_chat_id():
    from src.bot.commands import chatid_cmd
    u = _make_update(user_id=42)
    u.effective_chat.id = -1001234567890
    c = _make_context()
    await chatid_cmd(u, c)
    u.message.reply_text.assert_awaited_once()
    text = u.message.reply_text.await_args.args[0]
    assert "-1001234567890" in text