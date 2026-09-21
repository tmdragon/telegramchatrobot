"""BotService：python-telegram-bot Application 的异步包装。

两阶段生命周期：
1. init(token)：构造 Application + 验证 token（不 initialize / 不 polling）
2. register_handlers(app)：调用方在此窗口注册 handlers + 注入 bot_data
3. start_polling()：initialize → start → start_polling(drop_pending_updates=True)

stop() 反向关闭（updater → app → shutdown）。
send_message(chat_id, text)：发送消息；让异常向上抛，由调用方做重试。
get_chat_id_hint()：返回最近一次任意 update 的 from_user.id，admin 自助查询用。

PTB v20+ 契约：handlers 必须在 initialize 之前注册（参见 commands.py:13）。

Backward-compat: start(token) = init + start_polling 一气呵成。
⚠ start() 不在 init/start_polling 之间注册 handlers；新代码请直接调用
init() → register_handlers(app) → start_polling()。
"""
from __future__ import annotations

from typing import Optional

from telegram.ext import Application


class BotService:
    def __init__(self) -> None:
        self._app: Optional[Application] = None
        self._bot_username: Optional[str] = None
        self._last_update_user_id: Optional[int] = None

    async def init(self, token: str) -> None:
        """构造 Application + 验证 token（不 initialize / 不 polling）。

        调用方应在 init 之后、start_polling 之前向 self._app 注册 handlers
        并填充 bot_data（PTB v20+ 契约：handlers 必须在 initialize 之前注册）。

        Raises:
            RuntimeError: getMe 抛异常（token 无效 / 网络问题）
        """
        builder = Application.builder().token(token)
        app = builder.build()
        self._app = app

        me = await app.bot.get_me()
        if me is None or not getattr(me, "username", None):
            raise RuntimeError(f"getMe returned invalid user: {me!r}")
        self._bot_username = me.username

    async def start_polling(self) -> None:
        """启动 updater：initialize → start → start_polling。

        调用方必须先 init() 并在调用前完成 handlers 注册与 bot_data 注入。
        drop_pending_updates=True：丢弃 polling 启动前堆积的 update。

        Raises:
            RuntimeError: 未先调用 init()
        """
        if self._app is None:
            raise RuntimeError("BotService.init() must be called before start_polling()")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

    async def start(self, token: str) -> None:
        """Backward-compat: init + start_polling 一气呵成。

        ⚠ 不在 init/start_polling 之间注册 handlers；新代码请直接调用
        init() → register_handlers(app) → start_polling()。
        仅保留给不需要在 polling 前注册 handlers 的代码路径。
        """
        await self.init(token)
        await self.start_polling()

    async def stop(self) -> None:
        """关闭顺序：updater → app → shutdown。"""
        if self._app is None:
            return
        try:
            await self._app.updater.stop_polling()
        finally:
            try:
                await self._app.stop()
            finally:
                await self._app.shutdown()
        self._app = None

    async def send_message(self, chat_id: int | str, text: str) -> None:
        """发送 MarkdownV2 消息。Telegram API 异常向上抛。"""
        if self._app is None:
            raise RuntimeError("BotService not started")
        await self._app.bot.send_message(
            chat_id=chat_id, text=text, parse_mode="MarkdownV2"
        )

    async def get_chat_id_hint(self) -> Optional[int]:
        """返回最近一次任意 update 的 from_user.id，供 admin 自助查 chat_id。

        注：本任务仅暴露 getter；具体更新 _last_update_user_id 的逻辑留给 T3
        的 update listener（届时会有一个 no-op handler 写入该字段）。
        当前返回已记录的值或 None。
        """
        return self._last_update_user_id

    @property
    def username(self) -> Optional[str]:
        return self._bot_username