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
from src.models.project import Project
from src.models.status import StatusCode
from src.web.cache import ProjectCache


pytestmark = pytest.mark.asyncio


ADMIN_ID = 111


def _make_update(*, user_id: int, text: str | None = None, args: list[str] | None = None):
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat = MagicMock()
    update.effective_chat.id = 999
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
    assert "/force\\_broadcast" in text  # MarkdownV2 escapes _ as \_
    assert "/reload" in text
    assert "/dryrun" in text


# ---------- /status ----------

async def test_status_cmd_with_known_project():
    cache = ProjectCache()
    p = Project(
        project_id="PRJ-001", project_name="项目一",
        status=StatusCode.MAKING,
        status_changed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        sheets=[],
    )
    cache.replace([p])
    u = _make_update(user_id=42, args=["PRJ-001"])
    c = _make_context(args=["PRJ-001"])
    c.bot_data = {"cache": cache}
    # PTB 把 context.bot_data 暴露为 ContextTypes 属性；我们用 bot_data dict
    # status_cmd 通过 context.bot_data["cache"] 读取
    await status_cmd(u, c)
    u.message.reply_text.assert_awaited_once()
    text = u.message.reply_text.await_args.args[0]
    assert "PRJ-001" in text
    assert "MAKING" in text or "我方制作中" in text


async def test_status_cmd_with_unknown_project():
    cache = ProjectCache()
    cache.replace([])
    u = _make_update(user_id=42, args=["PRJ-NOPE"])
    c = _make_context(args=["PRJ-NOPE"])
    c.bot_data = {"cache": cache}
    await status_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "未找到" in text or "not found" in text.lower()


async def test_status_cmd_without_args_prompts():
    cache = ProjectCache()
    u = _make_update(user_id=42, args=[])
    c = _make_context(args=[])
    c.bot_data = {"cache": cache}
    await status_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "/status" in text or "项目编号" in text


# ---------- /projects ----------

async def test_projects_cmd_lists_all():
    cache = ProjectCache()
    p1 = Project(project_id="PRJ-001", project_name="项目一",
                 status=StatusCode.MAKING, status_changed_at=None, sheets=[])
    p2 = Project(project_id="PRJ-002", project_name=None,
                 status=StatusCode.PUBLISHED, status_changed_at=None, sheets=[])
    cache.replace([p1, p2])
    u = _make_update(user_id=42)
    c = _make_context()
    c.bot_data = {"cache": cache}
    await projects_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "PRJ-001" in text
    assert "PRJ-002" in text


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
    cache = ProjectCache()
    register_handlers(
        app, admin_chat_id=ADMIN_ID, cache=cache,
        broadcast_svc=MagicMock(), bot_service=MagicMock(), store=MagicMock(),
    )
    # 6 CommandHandler + 1 监听 user_id 的 MessageHandler（hint）= 至少 6 次
    assert app.add_handler.call_count >= 6