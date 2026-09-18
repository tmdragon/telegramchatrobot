"""BotService：python-telegram-bot Application 的异步包装。

职责：
- start(token): 构造 Application，调 getMe 验证 token，启动 polling
- stop(): 反向关闭（updater → app → shutdown）
- send_message(chat_id, text): 发送消息；让异常向上抛，由调用方（BroadcastSvc）做重试
- get_chat_id_hint(): 返回最近一次任意 update 的 from_user.id，admin 自助查询用

PTB v20+ 的 Application 是 asyncio.Application，所有 init/start/shutdown 协程化。
"""
from __future__ import annotations

from typing import Optional

from telegram.ext import Application


class BotService:
    def __init__(self) -> None:
        self._app: Optional[Application] = None
        self._bot_username: Optional[str] = None
        self._last_update_user_id: Optional[int] = None

    async def start(self, token: str) -> None:
        """构造 Application、验证 token、启动 polling。

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

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

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
