"""Telegram bot 命令处理。

- /status [PRJ-XXX]        所有人
- /projects                所有人
- /help                    所有人
- /force_broadcast         admin only
- /reload                  admin only
- /dryrun                  admin only

依赖通过 context.bot_data 注入：
  cache, store, mapping_repo, broadcast_svc, admin_chat_id, bot_service

注册：register_handlers(app, ...) 由 lifespan 在 start polling 之前调用。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from src.web.cache import ProjectCache

if TYPE_CHECKING:
    from src.bot.service import BotService
    from src.bot.broadcast import BroadcastSvc


HELP_TEXT = (
    "🤖 *checkGPRobot*\n\n"
    "/status PRJ-XXX — 查看项目当前状态\n"
    "/projects — 列出所有项目\n"
    "/help — 帮助\n"
    "/force\\_broadcast — 立即全员播报（管理员）\n"
    "/reload — 重读所有配置（管理员）\n"
    "/dryrun — 渲染文案预览，不发送（管理员）"
)


def _is_admin(update: Update, admin_chat_id: int) -> bool:
    user = update.effective_user
    return user is not None and user.id == admin_chat_id


async def _reply(update: Update, text: str) -> None:
    await update.message.reply_text(text, parse_mode="MarkdownV2")


# ---------- handlers ----------

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    cache: ProjectCache = context.bot_data["cache"]
    if not args:
        await _reply(update, "用法: `/status PRJ-XXX`")
        return
    pid = args[0]
    p = cache.get(pid)
    if p is None:
        await _reply(update, f"❓ 未找到项目 `{pid}`")
        return
    from src.web.filters import humanize_duration

    dwell = 0
    if p.status_changed_at:
        from datetime import datetime, timezone
        dwell = max(0, int((datetime.now(timezone.utc) - p.status_changed_at).total_seconds()))
    status_text = p.status.value if p.status else "未知"
    name_text = p.project_name or "（未命名）"
    await _reply(
        update,
        f"📊 *{p.project_id} {name_text}*\n"
        f"▸ 当前状态：`{status_text}`\n"
        f"▸ 停留时长：`{humanize_duration(dwell)}`",
    )


async def projects_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cache: ProjectCache = context.bot_data["cache"]
    summaries = cache.list_summaries()
    if not summaries:
        await _reply(update, "暂无项目。")
        return
    lines = ["📋 *所有项目*"]
    for s in summaries:
        status_text = s.status.value if s.status else "未知"
        lines.append(f"• `{s.project_id}` — `{status_text}`")
    await _reply(update, "\n".join(lines))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, HELP_TEXT)


async def force_broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = context.bot_data["admin_chat_id"]
    if not _is_admin(update, admin_id):
        await _reply(update, "⛔ 需要管理员权限。")
        return
    svc = context.bot_data["broadcast_svc"]
    result = await svc.broadcast_all(skip_if_no_change=True, dryrun=False)
    await _reply(
        update,
        f"✅ 播报完成: sent={result.get('sent', 0)} skipped={result.get('skipped', 0)} "
        f"failed={result.get('failed', 0)}",
    )


async def reload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = context.bot_data["admin_chat_id"]
    if not _is_admin(update, admin_id):
        await _reply(update, "⛔ 需要管理员权限。")
        return
    store = context.bot_data["store"]
    mapping_repo = context.bot_data["mapping_repo"]
    # load_all 是同步 gspread；包 to_thread
    import asyncio
    try:
        mappings = await asyncio.to_thread(mapping_repo.load_all)
    except Exception as e:  # noqa: BLE001
        await _reply(update, f"⚠ 重读失败: `{type(e).__name__}: {e}`")
        return
    for m in mappings:
        await asyncio.to_thread(store.save_mapping_snapshot, m)
    await _reply(update, f"🔄 已重读 {len(mappings)} 条映射。")


async def dryrun_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = context.bot_data["admin_chat_id"]
    if not _is_admin(update, admin_id):
        await _reply(update, "⛔ 需要管理员权限。")
        return
    svc = context.bot_data["broadcast_svc"]
    result = await svc.broadcast_all(skip_if_no_change=True, dryrun=True)
    preview = result.get("preview", "（无预览）")
    await _reply(update, f"🧪 *Dryrun 预览*\n```\n{preview}\n```")


# ---------- user_id 监听（hint 给 admin 用） ----------

async def _record_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """每条消息触发：把 from_user.id 存进 bot_data，供 admin 用 /help 时回显。"""
    bot_service: "BotService" = context.bot_data.get("bot_service")
    user = update.effective_user
    if bot_service is not None and user is not None:
        bot_service._last_update_user_id = user.id  # noqa: SLF001
    # 不回消息，避免打扰


def register_handlers(
    app: Any,
    *,
    admin_chat_id: int,
    cache: ProjectCache,
    broadcast_svc: "BroadcastSvc",
    bot_service: "BotService",
    store: Any,
) -> None:
    """注册 6 个命令 + 1 个 user_id 监听。"""
    app.bot_data["cache"] = cache
    app.bot_data["broadcast_svc"] = broadcast_svc
    app.bot_data["bot_service"] = bot_service
    app.bot_data["store"] = store
    app.bot_data["admin_chat_id"] = admin_chat_id
    # mapping_repo 由 lifespan 单独挂（reload 用）
    # 这里不直接读 mapping_repo，避免循环 import；lifespan 在 register 前补

    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("projects", projects_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("force_broadcast", force_broadcast_cmd))
    app.add_handler(CommandHandler("reload", reload_cmd))
    app.add_handler(CommandHandler("dryrun", dryrun_cmd))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, _record_user_id))