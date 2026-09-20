"""APScheduler AsyncIOScheduler 构建 + 广播 job。

build_scheduler：根据 broadcast_cfg.refresh_interval_minutes 切换模式：
- >0：事件驱动（interval 触发 refresh + 状态变化即播）
- =0：旧模式（cron 定时全员 broadcast_all）

无论哪种模式，都会注册：
- 滞留阈值播报：status 超过 N 小时在内部群提醒（按 stuck_status_hours 配置）
- 商店上架监测：SECOND_REVIEW > 24h 后定时访问商店地址，发现上架即更新 sheet
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.bot.broadcast import BroadcastSvc
from src.scheduler.config import BroadcastConfig
from src.store_checker import check_app_published
from src.web.cache import ProjectCache
from src.web.refresher import BackgroundRefresher


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def build_scheduler(
    broadcast_svc: BroadcastSvc,
    broadcast_cfg: BroadcastConfig,
    refresher: BackgroundRefresher | None = None,
) -> AsyncIOScheduler:
    """构造并配置 AsyncIOScheduler。"""
    scheduler = AsyncIOScheduler()

    if broadcast_cfg.refresh_interval_minutes > 0:
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

    # === 滞留阈值播报：每 30 分钟扫一次 ===
    if broadcast_cfg.stuck_status_hours:
        scheduler.add_job(
            _stuck_status_broadcast_wrapper,
            trigger=IntervalTrigger(minutes=30),
            args=(broadcast_svc, broadcast_cfg, refresher.cache if refresher else None),
            id="stuck-status-broadcast",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    # === 商店上架监测：每 N 分钟扫一次 SECOND_REVIEW 项目 ===
    if broadcast_cfg.store_monitor_interval_minutes > 0 and refresher is not None:
        scheduler.add_job(
            _store_monitor_wrapper,
            trigger=IntervalTrigger(minutes=broadcast_cfg.store_monitor_interval_minutes),
            args=(refresher, broadcast_svc, broadcast_cfg),
            id="store-monitor",
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


async def trigger_store_check_now(
    refresher: BackgroundRefresher,
    broadcast_svc: BroadcastSvc,
    broadcast_cfg: BroadcastConfig,
    project_id: str,
) -> dict:
    """手动触发单个项目的商店检查（忽略时间间隔）。"""
    cache = refresher.cache
    if cache is None:
        return {"ok": False, "reason": "no_cache"}
    proj = cache.get(project_id)
    if proj is None:
        return {"ok": False, "reason": "not_found"}
    if not proj.store_url:
        return {"ok": False, "reason": "no_store_url"}
    result = await check_app_published(
        proj.store_url, proxy=broadcast_cfg.store_monitor_proxy_url or None
    )
    now = datetime.now(timezone.utc)
    proj.last_store_check_at = now
    proj.last_store_check_result = "published" if result["published"] else "pending"

    if result["published"]:
        # 上架了！与定时任务同步：写 sheet + refresh + 提醒
        try:
            row = refresher._find_project_row(project_id)
            if row is None:
                await broadcast_svc.broadcast_internal_only_with_text(
                    f"⚠ 商店上架监测: 找不到 {project_id} 在 sheet 中的行"
                )
                return {
                    "ok": True, "published": True, "title": result.get("title"),
                    "reason": result.get("reason"), "sheet_updated": False,
                }
            await asyncio.to_thread(
                refresher.sheet_repo.update_cell_by_header,
                spreadsheet_id=refresher.cfg.spreadsheets[0].id,
                worksheet_name=refresher.cfg.spreadsheets[0].name,
                row=row,
                header_name="状态",
                new_value="已上架",
            )
            await refresher.refresh_now()
            # 触发 broadcast_project 让客户群立即收到"已上架"通知
            # （refresh_now 本身不广播；这是 _refresh_and_broadcast_wrapper 的工作）
            await broadcast_svc.broadcast_project(proj)
            await broadcast_svc.broadcast_internal_only_with_text(
                f"✅ 商店上架监测: {project_id} ({proj.project_name or '（未命名）'}) "
                f"已从 {proj.status.value if proj.status else '?'} → PUBLISHED。"
                f"检测到：{result.get('title') or '?'}"
            )
            return {
                "ok": True, "published": True, "title": result.get("title"),
                "reason": result.get("reason"), "sheet_updated": True,
            }
        except Exception as e:
            await broadcast_svc.broadcast_internal_only_with_text(
                f"⚠ 商店上架监测更新失败 {project_id}: {e}"
            )
            proj.last_store_check_result = "error"
            return {
                "ok": False, "published": True, "title": result.get("title"),
                "reason": f"update_failed: {e}",
            }
    else:
        next_at = now + timedelta(seconds=broadcast_cfg.store_monitor_min_hours * 3600)
        proj.next_store_check_at = next_at
        refresher.store_check_schedule[project_id] = next_at
        return {
            "ok": True, "published": False, "title": result.get("title"),
            "reason": result.get("reason"),
        }


async def _stuck_status_broadcast_wrapper(
    broadcast_svc: BroadcastSvc,
    broadcast_cfg: BroadcastConfig,
    cache: ProjectCache | None,
) -> None:
    """滞留阈值播报：超过 stuck_status_hours 设定的小时数 → 在内部群提醒。

    - CLIENT_REVIEW：内部群 + 项目映射群都发
    - 其他状态（MAKING / WAITING_SUBMIT 等）：只发内部群
    """
    if cache is None:
        return
    now = datetime.now(timezone.utc)
    for project in cache.list_projects():
        if project.status is None or project.status_changed_at is None:
            continue
        st_val = project.status.value
        threshold_hours = broadcast_cfg.stuck_status_hours.get(st_val)
        if not threshold_hours or threshold_hours <= 0:
            continue
        dwell = (now - project.status_changed_at).total_seconds() / 3600
        if dwell < threshold_hours:
            continue
        # CLIENT_REVIEW 发到内部群 + 项目群；其他只发内部群
        if project.status.value == "CLIENT_REVIEW":
            try:
                await broadcast_svc.broadcast_project(project)
            except Exception:  # noqa: BLE001
                pass
        else:
            try:
                await broadcast_svc.broadcast_internal_only(project)
            except Exception:  # noqa: BLE001
                pass


async def _store_monitor_wrapper(
    refresher: BackgroundRefresher,
    broadcast_svc: BroadcastSvc,
    broadcast_cfg: BroadcastConfig,
) -> None:
    """商店上架监测：SECOND_REVIEW 状态的项目，定时访问 store_url 判断是否已上架。

    - 每 N 分钟扫一次
    - 距上次检查 ≥ min_hours 才查（避免轰炸）
    - 未上架则下次随机 min~max 小时后查
    - 已上架 → 调 SheetRepo.update_cell 改 sheet 状态为 "已上架" → 触发下次 refresh → 自动播报
    - 检查结果写入 Project.next_store_check_at / last_store_check_at / last_store_check_result（UI 显示）
    """
    cache = refresher.cache
    if cache is None:
        return

    now = datetime.now(timezone.utc)
    min_seconds = broadcast_cfg.store_monitor_min_hours * 3600
    max_seconds = broadcast_cfg.store_monitor_max_hours * 3600

    for project in cache.list_projects():
        if project.status is None or project.status.value != "SECOND_REVIEW":
            continue
        if not project.store_url:
            continue
        # 距下次计划时间：now < next_check_at 则跳过
        scheduled = refresher.store_check_schedule.get(project.project_id)
        if scheduled is not None and now < scheduled:
            project.next_store_check_at = scheduled
            continue
        # 实际检查
        result = await check_app_published(
            project.store_url, proxy=broadcast_cfg.store_monitor_proxy_url or None
        )
        # 写入 Project 字段（UI 会读到）
        project.last_store_check_at = now
        project.last_store_check_result = "published" if result["published"] else "pending"
        if result["published"]:
            try:
                row = refresher._find_project_row(project.project_id)
                if row is None:
                    await broadcast_svc.broadcast_internal_only_with_text(
                        f"⚠ 商店上架监测: 找不到 {project.project_id} 在 sheet 中的行"
                    )
                    continue
                await asyncio.to_thread(
                    refresher.sheet_repo.update_cell_by_header,
                    spreadsheet_id=refresher.cfg.spreadsheets[0].id,
                    worksheet_name=refresher.cfg.spreadsheets[0].name,
                    row=row,
                    header_name="状态",
                    new_value="已上架",
                )
                # 触发 refresh 让 cache 立即同步
                await refresher.refresh_now()
                await broadcast_svc.broadcast_internal_only_with_text(
                    f"✅ 商店上架监测: {project.project_id} ({project.project_name or '（未命名）'}) "
                    f"已从 SECOND_REVIEW → PUBLISHED。检测到：{result.get('title') or '?'}"
                )
            except Exception as e:  # noqa: BLE001
                await broadcast_svc.broadcast_internal_only_with_text(
                    f"⚠ 商店上架监测更新失败 {project.project_id}: {e}"
                )
                project.last_store_check_result = "error"
        else:
            # 未上架：随机 4-8h 后下次查
            wait_seconds = random.uniform(min_seconds, max_seconds)
            next_at = now + timedelta(seconds=wait_seconds)
            project.next_store_check_at = next_at
            refresher.store_check_schedule[project.project_id] = next_at
