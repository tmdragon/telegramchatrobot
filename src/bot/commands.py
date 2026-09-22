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

from typing import TYPE_CHECKING, Any, Optional

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from src.web.cache import ProjectCache

if TYPE_CHECKING:
    from src.bot.service import BotService
    from src.bot.broadcast import BroadcastSvc


HELP_PUBLIC = (
    "🤖 *checkGPRobot* — 客户群可用指令\n\n"
    "*📋 `/projects`*\n"
    "列出本群映射的所有项目（含状态、停留时长）\n\n"
    "*📊 `/status <查询>`*\n"
    "查看项目当前状态。`查询` 支持以下三种形式：\n\n"
    "  1. *项目编号*（精确）\n"
    "     `/status PAK-001`\n"
    "     返回：项目名 / 包名 / 当前状态 / 停留时长\n\n"
    "  2. *包名*（模糊匹配）\n"
    "     `/status com.example.game1`\n"
    "     例如包名 `com.example.game1` 即匹配；大小写不敏感\n\n"
    "  3. *项目名*（模糊匹配）\n"
    "     `/status Tower up up`\n"
    "     部分关键词即可（如 `Tower` 也能匹配）\n\n"
    "  多个匹配 → 列出候选项目，让你用编号精确查：\n"
    "  `🔍 多个匹配 \`<查询>\`，请用编号：`\n"
    "  `  • \`PRJ-001\` 项目一 包名 \`com.example.game1\``\n\n"
    "*📦 `/info <查询>`*\n"
    "获取 app store 投放所需参数(类名/SHA/隐私政策/商店地址 等)。\n"
    "  `/info PRJ-001` — 按编号\n"
    "  `/info bmw` — 按包名模糊查\n"
    "  任何字段缺失会列出缺失项名称。\n\n"
    "*📞 联系管理员*\n"
    "遇到问题或需新指令，找管理员（机器人不报错就算正常）\n\n"
    "*❓ `/help`*\n"
    "  显示本帮助"
)

HELP_ADMIN = (
    "🤖 *checkGPRobot* — 管理员指令\n\n"
    "*📋 `/projects`*\n"
    "  列出所有项目（不限于本群）\n\n"
    "*📊 `/status <查询>`*\n"
    "  支持编号 / 包名 / 项目名 三种查询（详见客户群 /help）\n\n"
    "*🔄 `/force_broadcast`*\n"
    "  立即触发全员播报（不等到下个 cron tick）\n"
    "  ⚠ 不带 skip 跳过——会发\"无变化\"的项目到所有群\n\n"
    "*🔃 `/reload`*\n"
    "  重读所有配置（secrets.yaml / sheets.yaml）\n"
    "  适用：修改 sheet 配置、新增 spreadsheet 后\n\n"
    "*🧪 `/dryrun`*\n"
    "  渲染播报文案预览，不实际发送\n"
    "  用途：调试模板、查看即将发送的内容\n\n"
    "*🆔 `/chatid`*\n"
    "  显示当前 chat 的 ID（私聊或群）\n"
    "  用途：配置 admin_broadcast_chats 时需要群 ID\n\n"
    "*❓ `/help`*\n"
    "  显示本帮助"
)


def _is_admin(update: Update, admin_chat_id: int) -> bool:
    user = update.effective_user
    return user is not None and user.id == admin_chat_id


def _is_privileged_chat(
    chat_id_str: str,
    admin_chat_id: int,
    admin_broadcast_chats: list[str],
) -> bool:
    """判断当前 chat 是否能看所有项目：admin 私聊 + 内部管理群。"""
    if admin_chat_id and chat_id_str == str(admin_chat_id):
        return True
    return chat_id_str in (admin_broadcast_chats or [])


async def _load_chat_mappings(context, chat_id_str: str) -> list:
    """读取本 chat 启用映射的项目；mapping_repo 缺失或失败回退空列表。"""
    mapping_repo = context.bot_data.get("mapping_repo")
    if mapping_repo is None:
        return []
    import asyncio
    try:
        mappings = await asyncio.to_thread(mapping_repo.load_all)
    except Exception:  # noqa: BLE001
        return []
    return [m for m in mappings if str(m.chat_id) == chat_id_str and m.enabled]


async def _reply(update: Update, text: str) -> None:
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def _reply_plain(update: Update, text: str) -> None:
    """纯文本回复：用于含 MarkdownV2 保留字符（. ( ) 等）的帮助文档。"""
    await update.message.reply_text(text)


# ---------- handlers ----------

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    cache: ProjectCache = context.bot_data["cache"]
    if not args:
        await _reply(
            update,
            "用法:\n"
            "`/status PRJ-XXX` — 按项目编号查\n"
            "`/status <包名或项目名>` — 按包名/项目名模糊查",
        )
        return
    query = args[0].strip()

    chat = update.effective_chat
    chat_id_str = str(chat.id) if chat else ""
    admin_id = context.bot_data.get("admin_chat_id", 0)
    admin_broadcast_chats = context.bot_data.get("admin_broadcast_chats") or []
    privileged = _is_privileged_chat(chat_id_str, admin_id, admin_broadcast_chats)

    # 1) 精确按 project_id
    p = cache.get(query)
    # 2) 否则按包名 / 项目名 模糊匹配
    if p is None:
        q_lower = query.lower()
        candidates = []
        for proj in cache.list_projects():
            pkg = (proj.package_name or "").lower()
            name = (proj.project_name or "").lower()
            if q_lower in pkg or q_lower in name:
                candidates.append(proj)
        if len(candidates) == 1:
            p = candidates[0]
        elif len(candidates) > 1:
            lines = [f"🔍 多个匹配 `{query}`，请用编号："]
            for c in candidates[:10]:
                lines.append(f"  • `{c.project_id}` {c.project_name or '（未命名）'} 包名 `{c.package_name or '—'}`")
            await _reply(update, "\n".join(lines))
            return
        else:
            # 没匹配
            await _reply(update, f"❓ 未找到 `{query}`（按编号、包名、项目名都查过）")
            return

    # 客户群：校验映射
    if not privileged:
        mappings = await _load_chat_mappings(context, chat_id_str)
        if not any(m.project_id == p.project_id for m in mappings):
            await _reply(update, f"🔒 项目 `{p.project_id}` 不在本群映射中。")
            return

    from src.bot.templates import status_display_text
    from src.web.filters import humanize_duration

    dwell = 0
    if p.status_changed_at:
        from datetime import datetime, timezone
        dwell = max(0, int((datetime.now(timezone.utc) - p.status_changed_at).total_seconds()))
    status_text = status_display_text(p) or "未知"
    name_text = p.project_name or "（未命名）"
    pkg_text = p.package_name or "—"
    await _reply(
        update,
        f"📊 *`{p.project_id}` {name_text}*\n"
        f"▸ 包名：`{pkg_text}`\n"
        f"▸ 当前状态：`{status_text}`\n"
        f"▸ 停留时长：`{humanize_duration(dwell)}`",
    )


async def projects_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cache: ProjectCache = context.bot_data["cache"]
    chat = update.effective_chat
    chat_id_str = str(chat.id) if chat else ""
    admin_id = context.bot_data.get("admin_chat_id", 0)
    admin_broadcast_chats = context.bot_data.get("admin_broadcast_chats") or []
    privileged = _is_privileged_chat(chat_id_str, admin_id, admin_broadcast_chats)

    if privileged:
        summaries = cache.list_summaries()
        title = "📋 *所有项目*"
    else:
        # 客户群：按映射过滤
        mappings = await _load_chat_mappings(context, chat_id_str)
        allowed_pids = {m.project_id for m in mappings}
        summaries = [s for s in cache.list_summaries() if s.project_id in allowed_pids]
        title = "📋 *本群项目*"

    if not summaries:
        await _reply(update, "本群暂无关联项目。" if not privileged else "暂无项目。")
        return
    lines = [title]
    from src.bot.templates import status_display_text
    for s in summaries:
        status_text = status_display_text(s) or "未知"
        pkg = f" — `{s.package_name}`" if s.package_name else ""
        lines.append(f"• `{s.project_id}`{pkg} — `{status_text}`")
    await _reply(update, "\n".join(lines))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    chat_id_str = str(chat.id) if chat else ""
    admin_id = context.bot_data.get("admin_chat_id", 0)
    admin_broadcast_chats = context.bot_data.get("admin_broadcast_chats") or []
    privileged = _is_privileged_chat(chat_id_str, admin_id, admin_broadcast_chats)
    # 客户群只看公开指令；管理员 / 内部群看完整指令
    # 用纯文本：含 MarkdownV2 保留字符（. ( ) : / 等）多
    await _reply_plain(update, HELP_ADMIN if privileged else HELP_PUBLIC)


async def chatid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """回复当前 chat 的 ID（私聊/群都通用），用于 admin 自助查群 chat_id。"""
    chat = update.effective_chat
    cid = chat.id if chat is not None else None
    if cid is None:
        await _reply(update, "❓ 无法获取 chat id")
        return
    await _reply(update, f"ℹ️ This chat's ID: `{cid}`")


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


async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/info [项目编号或包名片段] — 返回 app store 投放所需字段(类名/SHA/隐私政策/商店地址 等)。

    模糊匹配:精确 project_id 优先;否则按 project_id / package_name 包含子串匹配。
    多匹配 → 列出候选。多匹配时不会泄露字段(避免发错对象)。
    任何人可用(not admin-only),客户群里方便投放部署时取参数。
    """
    cache: ProjectCache = context.bot_data["cache"]
    args = context.args or []
    if not args:
        # 纯文本:去掉 Markdown 反引号(否则用户会看到字面的 ` 字符)
        await _reply_plain(
            update,
            "用法:\n"
            "/info PRJ-XXX — 按项目编号精确查\n"
            "/info <包名片段> — 按包名模糊查(如 bmw)",
        )
        return
    query = args[0].strip()

    # 1) 精确按 project_id
    p = cache.get(query)
    if p is None:
        q_lower = query.lower()
        candidates = []
        for proj in cache.list_projects():
            pid = (proj.project_id or "").lower()
            pkg = (proj.package_name or "").lower()
            if q_lower in pid or q_lower in pkg:
                candidates.append(proj)
        if len(candidates) == 1:
            p = candidates[0]
        elif len(candidates) > 1:
            lines = [f"🔍 多个匹配 {query}，请用编号："]
            for c in candidates[:10]:
                lines.append(f"  • {c.project_id} {c.project_name or '（未命名）'} 包名 {c.package_name or '—'}")
            await _reply_plain(update, "\n".join(lines))
            return
        else:
            await _reply_plain(update, f"❓ 未找到 {query}（按编号、包名都查过）")
            return

    # 2) 提取字段(从 sheets[*].fields[*].recognized_as 找)
    # 每个 recognized_as 取第一个非空值
    found: dict[str, str] = {}
    for sv in p.sheets:
        for f in sv.fields:
            if f.recognized_as and f.value and f.recognized_as not in found:
                found[f.recognized_as] = str(f.value).strip()

    # 2.5) 控制点:只服务于已上架(PUBLISHED)项目。
    # 其他状态(制作中/已下架/未知)不返回投放参数,
    # 避免泄露未发布包的真实 URL/密钥,或给客户错误的部署参数。
    from src.models.status import StatusCode
    from src.bot.templates import status_display_text

    if p.status != StatusCode.PUBLISHED:
        status_text = status_display_text(p) or (p.status_raw or "未知")
        await _reply_plain(
            update,
            f"{p.project_id} 该包未上架(当前状态:{status_text}),无法提取投放信息",
        )
        return

    # 期望字段(显示用中文标签)
    expected = [
        ("project_id", "项目编号"),
        ("package_name", "包名"),
        ("class_name", "类名"),
        ("sha1", "SHA-1"),
        ("sha256", "SHA-256"),
        ("hash_value", "hash值"),
        ("privacy_policy", "隐私政策"),
        ("store_url", "投放地址"),
    ]
    missing = [(key, label) for key, label in expected if key not in found or not found[key]]

    if missing:
        missing_labels = ", ".join(label for _, label in missing)
        await _reply_plain(
            update,
            f"{p.project_id} 项目投放信息提取失败\n"
            f"缺失 {missing_labels} 信息，请补充",
        )
        return

    # 3) 渲染(对齐:用户给的格式里,"包       名" 中间 7 空格,对应 "项目编号" 4 字符 → 间距匹配 4 字符)
    # SHA-256: 用 ":" 后无空格,跟其他 label 后 ":" 不一致(用户原样)
    labels = [
        ("项目编号:", found["project_id"]),
        ("包       名:", found["package_name"]),
        ("类       名:", found["class_name"]),
        ("SHA-1    :", found["sha1"]),
        ("SHA-256:", found["sha256"]),
        ("hash值   :", found["hash_value"]),
        ("隐私政策:", found["privacy_policy"]),
        ("投放地址:", found["store_url"]),
    ]
    sep = "--------------------" + f"{p.project_id}项目投放信息如下" + "--------------------"
    footer = "----------------------------------------------------------"
    lines = [sep]
    for key, value in labels:
        lines.append(f"{key}{value}")
    lines.append(footer)
    # 用 _reply_plain(纯文本)而不是 _reply(MarkdownV2)
    # 因为字段值里的 . (在 SHA-1: A1:83:FC:CE:B0:...) 是 MarkdownV2 保留字符,
    # 会让 parse_mode 解析失败导致消息发不出去。
    await _reply_plain(update, "\n".join(lines))


def register_handlers(
    app: Any,
    *,
    admin_chat_id: int,
    cache: ProjectCache,
    broadcast_svc: "BroadcastSvc",
    bot_service: "BotService",
    store: Any,
    admin_broadcast_chats: Optional[list[str]] = None,
) -> None:
    """注册 6 个命令 + 1 个 user_id 监听。"""
    app.bot_data["cache"] = cache
    app.bot_data["broadcast_svc"] = broadcast_svc
    app.bot_data["bot_service"] = bot_service
    app.bot_data["store"] = store
    app.bot_data["admin_chat_id"] = admin_chat_id
    app.bot_data["admin_broadcast_chats"] = list(admin_broadcast_chats or [])
    # mapping_repo 由 lifespan 单独挂（reload 用）
    # 这里不直接读 mapping_repo，避免循环 import；lifespan 在 register 前补

    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("projects", projects_cmd))
    app.add_handler(CommandHandler("chatid", chatid_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("force_broadcast", force_broadcast_cmd))
    app.add_handler(CommandHandler("reload", reload_cmd))
    app.add_handler(CommandHandler("dryrun", dryrun_cmd))
    app.add_handler(CommandHandler("info", info_cmd))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, _record_user_id))