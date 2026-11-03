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
from src.models.payment import PaymentStatus
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

async def test_help_cmd_public_for_customer_chat():
    """客户群：/help 只显示 /projects、/status 及详细使用说明。"""
    u = _make_update(user_id=42, chat_id=-100123)  # 非 admin
    c = _make_context()
    c.bot_data = {"admin_chat_id": ADMIN_ID, "admin_broadcast_chats": []}
    await help_cmd(u, c)
    u.message.reply_text.assert_awaited_once()
    text = u.message.reply_text.await_args.args[0]
    # 客户群应看到
    assert "/projects" in text
    assert "/status" in text
    assert "/help" in text
    # /status 使用说明要点
    assert "项目编号" in text
    assert "包名" in text
    assert "项目名" in text
    # 不应看到管理员指令
    assert "/force_broadcast" not in text
    assert "/reload" not in text
    assert "/dryrun" not in text
    assert "/chatid" not in text


async def test_help_cmd_admin_for_admin_chat():
    """管理员 / 内部群：/help 显示完整指令。"""
    u = _make_update(user_id=ADMIN_ID, chat_id=ADMIN_ID)
    c = _make_context()
    c.bot_data = {"admin_chat_id": ADMIN_ID, "admin_broadcast_chats": []}
    await help_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "/projects" in text
    assert "/status" in text
    assert "/force_broadcast" in text
    assert "/reload" in text
    assert "/dryrun" in text
    assert "/chatid" in text


async def test_help_cmd_admin_for_internal_broadcast_chat():
    """内部管理群（admin_broadcast_chats）：也是完整指令。"""
    internal_chat = "-1004465951132"
    u = _make_update(user_id=42, chat_id=internal_chat)
    c = _make_context()
    c.bot_data = {
        "admin_chat_id": ADMIN_ID,
        "admin_broadcast_chats": [internal_chat],
    }
    await help_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "/force_broadcast" in text


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


def _projects_cache(*projects: Project) -> ProjectCache:
    cache = ProjectCache()
    cache.replace(list(projects))
    return cache


def _customer_ctx(cache: ProjectCache, chat_id: int = -100123):
    """客户群 context：cache 里所有项目都映射到该群。"""
    mapping_repo = MagicMock()
    mapping_repo.load_all = MagicMock(return_value=[
        Mapping(project_id=p.project_id, chat_id=str(chat_id), note="",
                enabled=True, last_broadcast_at=None,
                last_broadcast_status=None, last_error=None)
        for p in cache.list_projects()
    ])
    c = _make_context()
    c.bot_data = {
        "cache": cache, "mapping_repo": mapping_repo,
        "admin_chat_id": ADMIN_ID,
        "admin_broadcast_chats": [],
    }
    return c


async def test_projects_cmd_marks_settled_project():
    """已结算项目行末显示 💰 已结算"""
    cache = _projects_cache(Project(
        project_id="PAK-001", project_name="项目一",
        package_name="com.example.pkg1",
        status=StatusCode.MAKING, status_changed_at=None, sheets=[],
        payment_status=PaymentStatus.PAID,
    ))
    u = _make_update(user_id=42, chat_id=-100123)
    await projects_cmd(u, _customer_ctx(cache))
    text = u.message.reply_text.await_args.args[0]
    assert "已结算" in text
    assert "未结算" not in text


async def test_projects_cmd_marks_unsettled_project():
    """未结算项目行末显示 ⚠️ 未结算"""
    cache = _projects_cache(Project(
        project_id="PAK-001", project_name="项目一",
        package_name="com.example.pkg1",
        status=StatusCode.MAKING, status_changed_at=None, sheets=[],
        payment_status=PaymentStatus.UNPAID,
    ))
    u = _make_update(user_id=42, chat_id=-100123)
    await projects_cmd(u, _customer_ctx(cache))
    text = u.message.reply_text.await_args.args[0]
    assert "未结算" in text
    assert "已结算" not in text


async def test_projects_cmd_missing_payment_counts_as_unsettled():
    """sheet 没有支付列（payment_status 为空）→ 按未结算显示"""
    cache = _projects_cache(Project(
        project_id="PAK-001", project_name="项目一",
        package_name="com.example.pkg1",
        status=StatusCode.MAKING, status_changed_at=None, sheets=[],
        payment_status=None,
    ))
    u = _make_update(user_id=42, chat_id=-100123)
    await projects_cmd(u, _customer_ctx(cache))
    text = u.message.reply_text.await_args.args[0]
    assert "未结算" in text


async def test_projects_cmd_marks_settled_and_unsettled_together():
    """同一群里已结算与未结算项目一起播报，各自带标记"""
    cache = _projects_cache(
        Project(
            project_id="PAK-001", project_name="项目一",
            package_name="com.example.pkg1",
            status=StatusCode.MAKING, status_changed_at=None, sheets=[],
            payment_status=PaymentStatus.PAID,
        ),
        Project(
            project_id="PAK-002", project_name="项目二",
            package_name="com.example.pkg2",
            status=StatusCode.PUBLISHED, status_changed_at=None, sheets=[],
            payment_status=PaymentStatus.UNPAID,
        ),
    )
    u = _make_update(user_id=42, chat_id=-100123)
    await projects_cmd(u, _customer_ctx(cache))
    text = u.message.reply_text.await_args.args[0]
    assert "PAK-001" in text
    assert "PAK-002" in text
    assert "已结算" in text
    assert "未结算" in text


# ---------- /projects 分组表格 ----------

def _dwidth(text: str) -> int:
    """显示宽度：全角/中文算 2 列。测试用独立实现，不复用被测代码。"""
    import unicodedata
    total = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def _code_block_lines(text: str) -> list[str]:
    """取出 ``` 代码块里的行（去掉围栏）。"""
    lines: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.strip() == "```":
            inside = not inside
            continue
        if inside:
            lines.append(line)
    return lines


def _field_starts(line: str) -> list[int]:
    """每个字段的起始显示列（字段以 2 个以上空格分隔）。"""
    import re
    starts: list[int] = []
    for m in re.finditer(r"\S+(?: \S+)*", line):
        starts.append(_dwidth(line[:m.start()]))
    return starts


async def test_projects_cmd_renders_grouped_code_block_table():
    """每个状态组一个等宽代码块表格"""
    cache = _projects_cache(
        Project(
            project_id="PAK-001", project_name="项目一",
            package_name="com.example.pkg1",
            status=StatusCode.MAKING, status_changed_at=None, sheets=[],
            payment_status=PaymentStatus.PAID,
        ),
        Project(
            project_id="PAK-002", project_name="项目二",
            package_name="com.example.pkg2",
            status=StatusCode.MAKING, status_changed_at=None, sheets=[],
            payment_status=PaymentStatus.UNPAID,
        ),
    )
    u = _make_update(user_id=42, chat_id=-100123)
    await projects_cmd(u, _customer_ctx(cache))
    text = u.message.reply_text.await_args.args[0]
    assert text.count("```") == 2  # 一个状态组 → 一对围栏
    table = _code_block_lines(text)
    assert table[0].startswith("项目编号")
    assert "包名" in table[0]
    assert "结算" in table[0]
    assert set(table[1]) == {"-"}  # 表头下的分隔线
    assert "PAK-001" in table[2]
    assert "com.example.pkg1" in table[2]
    assert "已结算" in table[2]


async def test_projects_cmd_group_heading_escapes_count_parentheses():
    """组标题的数量括号要按 MarkdownV2 转义，否则整条消息发不出去"""
    cache = _projects_cache(Project(
        project_id="PAK-001", project_name="项目一",
        status=StatusCode.MAKING, status_changed_at=None, sheets=[],
        payment_status=PaymentStatus.PAID,
    ))
    u = _make_update(user_id=42, chat_id=-100123)
    await projects_cmd(u, _customer_ctx(cache))
    text = u.message.reply_text.await_args.args[0]
    assert "🟣 *我方制作中* \\(1\\)" in text
    # 未转义的裸括号会让 Telegram 解析失败
    assert "(1)" not in text


async def test_projects_cmd_published_group_first_off_shelf_last():
    """已发布置顶，已下架收尾"""
    cache = _projects_cache(
        Project(project_id="PAK-001", project_name="一",
                status=StatusCode.OFF_SHELF, status_changed_at=None, sheets=[],
                payment_status=PaymentStatus.PAID),
        Project(project_id="PAK-002", project_name="二",
                status=StatusCode.SECOND_REVIEW, status_changed_at=None, sheets=[],
                payment_status=PaymentStatus.PAID),
        Project(project_id="PAK-003", project_name="三",
                status=StatusCode.PUBLISHED, status_changed_at=None, sheets=[],
                payment_status=PaymentStatus.PAID),
    )
    u = _make_update(user_id=42, chat_id=-100123)
    await projects_cmd(u, _customer_ctx(cache))
    text = u.message.reply_text.await_args.args[0]
    i_published = text.index("已发布")
    i_second = text.index("复审中")
    i_off = text.index("已下架")
    assert i_published < i_second < i_off


async def test_projects_cmd_line_omits_status_text():
    """状态只出现在组标题，行内不再重复"""
    cache = _projects_cache(Project(
        project_id="PAK-001", project_name="项目一",
        package_name="com.example.pkg1",
        status=StatusCode.PUBLISHED, status_raw="已上架",
        status_changed_at=None, sheets=[],
        payment_status=PaymentStatus.PAID,
    ))
    u = _make_update(user_id=42, chat_id=-100123)
    await projects_cmd(u, _customer_ctx(cache))
    text = u.message.reply_text.await_args.args[0]
    table = _code_block_lines(text)
    # 表头 + 分隔线 + 1 行数据：数据行里只有编号/包名/结算
    data_line = table[2]
    assert "已上架" not in data_line
    assert "已发布" not in data_line
    assert "PAK-001" in data_line


async def test_projects_cmd_table_columns_aligned():
    """表格每一列在所有行里的起始列号必须一致"""
    cache = _projects_cache(
        Project(project_id="PAK-001", project_name="一",
                package_name="com.example.short",
                status=StatusCode.PUBLISHED, status_changed_at=None, sheets=[],
                payment_status=PaymentStatus.PAID),
        Project(project_id="PAK-0680(6514b)", project_name="二",
                package_name="com.example.a.very.long.package.name",
                status=StatusCode.PUBLISHED, status_changed_at=None, sheets=[],
                payment_status=PaymentStatus.UNPAID),
    )
    u = _make_update(user_id=42, chat_id=-100123)
    await projects_cmd(u, _customer_ctx(cache))
    text = u.message.reply_text.await_args.args[0]
    table = _code_block_lines(text)
    data_rows = [ln for ln in table if not set(ln) == {"-"}]
    starts = [_field_starts(ln) for ln in data_rows]
    assert all(s == starts[0] for s in starts), starts


async def test_projects_cmd_unknown_status_gets_own_group():
    """状态识别不出来的项目按原始文字单独成组"""
    cache = _projects_cache(Project(
        project_id="PAK-001", project_name="项目一",
        status=None, status_raw="待确认",
        status_changed_at=None, sheets=[],
        payment_status=PaymentStatus.PAID,
    ))
    u = _make_update(user_id=42, chat_id=-100123)
    await projects_cmd(u, _customer_ctx(cache))
    text = u.message.reply_text.await_args.args[0]
    assert "待确认" in text
    assert "PAK-001" in text


async def test_projects_cmd_admin_sees_payment_markers():
    """admin 私聊看全表时也带结算标记"""
    cache = _projects_cache(
        Project(
            project_id="PRJ-001", project_name="项目一",
            status=StatusCode.MAKING, status_changed_at=None, sheets=[],
            payment_status=PaymentStatus.PAID,
        ),
        Project(
            project_id="PRJ-002", project_name="项目二",
            status=StatusCode.PUBLISHED, status_changed_at=None, sheets=[],
            payment_status=PaymentStatus.UNPAID,
        ),
    )
    u = _make_update(user_id=ADMIN_ID, chat_id=ADMIN_ID)
    c = _make_context()
    c.bot_data = {"cache": cache, "admin_chat_id": ADMIN_ID,
                  "admin_broadcast_chats": []}
    await projects_cmd(u, c)
    text = u.message.reply_text.await_args.args[0]
    assert "已结算" in text
    assert "未结算" in text


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

def test_settle_cmd_sends_photo_when_configured(monkeypatch):
    """settle_cmd 应该从 store 拿 file_id + wallet,然后 bot.send_photo。"""
    import asyncio
    from src.bot import commands

    fake_info = {"qr_file_id": "AgAC_xyz", "wallet_address": "0xABC"}
    fake_store = MagicMock()
    fake_store.get_payment_info.return_value = fake_info
    fake_bot_service = MagicMock()
    fake_bot_service.send_photo = AsyncMock()

    update = MagicMock()
    update.effective_chat.id = -1001
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.bot_data = {
        "store": fake_store,
        "bot_service": fake_bot_service,
        "admin_chat_id": 999,
    }

    asyncio.run(commands.settle_cmd(update, context))
    fake_bot_service.send_photo.assert_awaited_once()
    call = fake_bot_service.send_photo.call_args
    assert call.kwargs["chat_id"] == -1001
    assert call.kwargs["file_id"] == "AgAC_xyz"
    assert "0xABC" in call.kwargs["caption"]


def test_settle_cmd_no_config_sends_text_only(monkeypatch):
    """未配置时不应调 send_photo,只发提示文本。"""
    import asyncio
    from src.bot import commands

    fake_store = MagicMock()
    fake_store.get_payment_info.return_value = None
    fake_bot_service = MagicMock()
    fake_bot_service.send_photo = AsyncMock()
    update = MagicMock()
    update.effective_chat.id = -1002
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.bot_data = {
        "store": fake_store,
        "bot_service": fake_bot_service,
        "admin_chat_id": 999,
    }

    asyncio.run(commands.settle_cmd(update, context))
    fake_bot_service.send_photo.assert_not_called()
    update.message.reply_text.assert_awaited_once()
    msg = update.message.reply_text.call_args.args[0]
    assert "未配置" in msg or "尚未配置" in msg


def test_settle_cmd_caption_escapes_markdownv2_reserved_chars():
    """settle_cmd 发的 caption 在 MarkdownV2 模式下不应含未转义的 reserved 字符。

    之前 Bug:caption 含 "(拼音全拼)" + 未转义的 wallet 地址 → Telegram 报
    "BadRequest: Can't parse entities: character '(' is reserved and must be escaped"
    修复:caption 里任何 (、)、.、- 等 MarkdownV2 reserved 字符都要 \\ 前缀。
    """
    import asyncio
    from src.bot import commands

    # wallet_address 含 . 和 _ (都是 MarkdownV2 reserved)
    fake_info = {"qr_file_id": "AgAC_xyz", "wallet_address": "0xABC.test-wallet"}
    fake_store = MagicMock()
    fake_store.get_payment_info.return_value = fake_info
    fake_bot_service = MagicMock()
    fake_bot_service.send_photo = AsyncMock()

    update = MagicMock()
    update.effective_chat.id = -1003
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.bot_data = {
        "store": fake_store,
        "bot_service": fake_bot_service,
        "admin_chat_id": 999,
    }

    asyncio.run(commands.settle_cmd(update, context))
    caption = fake_bot_service.send_photo.call_args.kwargs["caption"]

    # 静态文案里"(拼音全拼)"必须已被 escape
    assert r"\(拼音全拼\)" in caption, (
        f"caption 应含 \\\\(拼音全拼\\\\),实际: {caption!r}"
    )
    # 钱包地址里的 . 必须被 escape(以 \\. 形式出现)
    # 注意:wallet 在 ``` code block ``` 里,所以里面的 . 仍需 escape
    assert r"0xABC\.test\-wallet" in caption, (
        f"caption 应含转义后的 wallet 地址,实际: {caption!r}"
    )
