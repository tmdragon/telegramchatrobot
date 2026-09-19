"""APScheduler AsyncIOScheduler 构建 + 广播 job。

build_scheduler: 注册 N 个 cron 触发器（每个 times 一条），全部指向 broadcast_job。
broadcast_job: 工作日过滤（weekdays_only）→ 调 BroadcastSvc.broadcast_all。
"""
from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.bot.broadcast import BroadcastSvc
from src.scheduler.config import BroadcastConfig


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def build_scheduler(
    broadcast_svc: BroadcastSvc,
    broadcast_cfg: BroadcastConfig,
) -> AsyncIOScheduler:
    """构造并配置 AsyncIOScheduler，注册 broadcast job。"""
    scheduler = AsyncIOScheduler()

    for t in broadcast_cfg.times:
        hour, minute = _parse_hhmm(t)
        trigger = CronTrigger(hour=hour, minute=minute, timezone="UTC")
        scheduler.add_job(
            _broadcast_job_wrapper,
            trigger=trigger,
            args=(broadcast_svc, broadcast_cfg),
            id=f"broadcast-{t}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    return scheduler


async def _broadcast_job_wrapper(
    broadcast_svc: BroadcastSvc, broadcast_cfg: BroadcastConfig
) -> None:
    """被 APScheduler 调用的同步入口；内部再分流。"""
    if broadcast_cfg.weekdays_only:
        # weekday(): Monday=0 ... Sunday=6
        if datetime.now(timezone.utc).weekday() >= 5:
            return
    await broadcast_svc.broadcast_all(
        skip_if_no_change=broadcast_cfg.skip_if_no_change,
        dryrun=False,
    )
