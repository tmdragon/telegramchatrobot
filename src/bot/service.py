"""BotService：python-telegram-bot Application 的异步包装。

两阶段生命周期：
1. init(token)：构造 Application + 验证 token（不 initialize / 不 polling）
2. register_handlers(app)：调用方在此窗口注册 handlers + 注入 bot_data
3. start_polling()：initialize → start → 启动我们自己的 polling loop

stop() 反向关闭（cancel polling → app → shutdown）。
send_message(chat_id, text)：发送消息；让异常向上抛，由调用方做重试。
get_chat_id_hint()：返回最近一次任意 update 的 from_user.id，admin 自助查询用。

PTB v20+ 契约：handlers 必须在 initialize 之前注册（参见 commands.py:13）。

为什么不用 PTB 自带的 updater.start_polling()？
- PTB 的 _network_loop_retry 在 NetworkError 之外的"未知异常"上会 raise
- 这个 raise 会被 asyncio 捕获并传给 uvicorn,导致整个进程退出
- 实测 bot 崩溃触发了至少 5 次(每次 inline-edit、/info 一起死)
- 自定义 loop:catch 所有异常,退避后重试,不让进程死
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from telegram.ext import Application

log = logging.getLogger(__name__)


class BotService:
    def __init__(self) -> None:
        self._app: Optional[Application] = None
        self._bot_username: Optional[str] = None
        self._last_update_user_id: Optional[int] = None
        self._last_update_id: int = 0
        self._shutdown_event: Optional[asyncio.Event] = None
        self._polling_task: Optional[asyncio.Task] = None

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
        """启动我们的 polling 循环(自己 catch 异常,不让 uvicorn 死)。

        调用方必须先 init() 并在调用前完成 handlers 注册与 bot_data 注入。
        """
        if self._app is None:
            raise RuntimeError("BotService.init() must be called before start_polling()")
        await self._app.initialize()
        await self._app.start()
        # 启动我们的 polling 任务
        self._shutdown_event = asyncio.Event()
        self._polling_task = asyncio.create_task(self._polling_loop())

    async def _polling_loop(self, initial_backoff: float = 1.0) -> None:
        """我们自己的 polling 循环,替代 PTB 自带的 _network_loop_retry。

        - 10s long polling(可快速响应 shutdown)
        - 任意异常 catch 后 sleep 重试,带退避(初始 1s → 最长 30s)
        - 维护 _last_update_id 避免重复 for 同一个 update
        - 正常路径:get_updates 返回 → 逐个 process_update → 回到循环

        Args:
            initial_backoff: 测试用,允许更短的初始退避。
        """
        assert self._app is not None and self._shutdown_event is not None
        backoff = initial_backoff
        while not self._shutdown_event.is_set():
            try:
                updates = await self._app.bot.get_updates(
                    offset=self._last_update_id + 1 if self._last_update_id else None,
                    allowed_updates=None,
                    timeout=10,
                )
                backoff = initial_backoff  # 成功后重置
                for upd in updates:
                    self._last_update_id = max(self._last_update_id, upd.update_id)
                    await self._app.process_update(upd)
                    if self._shutdown_event.is_set():
                        break  # 下一个 loop iteration 也会退出,这里早一点
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                log.exception("polling crashed, retrying in %.1fs: %s", backoff, e)
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(), timeout=backoff
                    )
                    break  # shutdown 在 backoff 期间被触发
                except asyncio.TimeoutError:
                    pass  # backoff 到期,继续重试
                backoff = min(backoff * 2, 30.0)

    async def start(self, token: str) -> None:
        """Backward-compat: init + start_polling 一气呵成。

        ⚠ 不在 init/start_polling 之间注册 handlers；新代码请直接调用
        init() → register_handlers(app) → start_polling()。
        仅保留给不需要在 polling 前注册 handlers 的代码路径。
        """
        await self.init(token)
        await self.start_polling()

    async def stop(self) -> None:
        """关闭顺序：cancel polling → app → shutdown。"""
        if self._app is None:
            return
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        if self._polling_task is not None:
            try:
                await asyncio.wait_for(self._polling_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._polling_task.cancel()
            self._polling_task = None
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
        """返回最近一次任意 update 的 from_user.id，供 admin 自助查 chat_id。"""
        return self._last_update_user_id

    @property
    def username(self) -> Optional[str]:
        return self._bot_username