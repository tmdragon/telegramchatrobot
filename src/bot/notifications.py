"""管理员告警通道。

notify_admin(bot_service, admin_chat_id, message):
    1s/2s/4s 指数退避；至少一次成功 → True；全失败 → False（不抛）。

供 BroadcastSvc 在 partial failure 时调用。
"""
from __future__ import annotations

import asyncio
from typing import Union

from src.bot.service import BotService


async def notify_admin(
    bot_service: BotService,
    admin_chat_id: Union[int, str],
    message: str,
    *,
    retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0),
) -> bool:
    """发送管理员告警；返回 True 表示至少一次成功。"""
    last_error: Exception | None = None
    for attempt in range(len(retry_delays) + 1):
        try:
            await bot_service.send_message(admin_chat_id, message)
            return True
        except Exception as e:  # noqa: BLE001
            last_error = e
            if attempt < len(retry_delays):
                await asyncio.sleep(retry_delays[attempt])
    # 全失败：返回 False；不抛（让 BroadcastSvc 继续跑）
    return False
