"""APScheduler AsyncIOScheduler 构建 + 广播 job。

build_scheduler：根据 broadcast_cfg.refresh_interval_minutes 切换模式：
- >0：事件驱动（interval 触发 refresh + 状态变化即播）
- =0：旧模式（cron 定时全员 broadcast_all）
"""
from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.bot.broadcast import BroadcastSvc
from src.scheduler.config import BroadcastConfig
from src.web.refresher import BackgroundRefresher


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def build_scheduler(
    broadcast_svc: BroadcastSvc,
    broadcast_cfg: BroadcastConfig,
    refresher: BackgroundRefresher | None = None,
) -> AsyncIOScheduler:
    """构造并配置 AsyncIOScheduler。

    Args:
        broadcast_svc: 播报服务
        broadcast_cfg: 调度配置
        refresher: 事件驱动模式必传；用于每 N 分钟拉一次 sheet 并检测变化
    """
    scheduler = AsyncIOScheduler()

    if broadcast_cfg.refresh_interval_minutes > 0:
        # 事件驱动：每 N 分钟 refresh → 检测变化 → 立即播报
        if refresher is None:
            raise ValueError(
                "refresh_interval_minutes > 0 requires a BackgroundRefresher"
            )
        scheduler.add_job(
            _refresh_and_broadcast_wrapper,
            trigger=IntervalTrigger(minutes=broadcast_cfg.refresh_interval_minutes),
            args=(refresher, broadcast_svc),
            id="refresh-and-broadcast",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    else:
        # 旧模式：cron 定时全员 broadcast_all（保留作为可选 fallback）
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


async def _refresh_and_broadcast_wrapper(
    refresher: BackgroundRefresher,
    broadcast_svc: BroadcastSvc,
) -> None:
    """定时 refresh sheet → 检测变化 → 立即播报每个变化的项目。"""
    result = await refresher.refresh_now()
    for project in result.get("changes", []):
        try:
            await broadcast_svc.broadcast_project(project)
        except Exception:  # noqa: BLE001
            # 单项目失败不影响整体循环；下个项目继续
            pass


async def _broadcast_job_wrapper(
    broadcast_svc: BroadcastSvc, broadcast_cfg: BroadcastConfig
) -> None:
    """cron 模式入口：工作日过滤 → 全员 broadcast_all。"""
    if broadcast_cfg.weekdays_only:
        if datetime.now(timezone.utc).weekday() >= 5:
            return
    await broadcast_svc.broadcast_all(
        skip_if_no_change=broadcast_cfg.skip_if_no_change,
        dryrun=False,
    )
