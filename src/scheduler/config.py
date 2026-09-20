"""scheduler.yaml 加载与校验。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass
class BroadcastConfig:
    times: list[str] = field(default_factory=lambda: ["09:00", "18:00"])
    weekdays_only: bool = True
    skip_if_no_change: bool = True
    per_status_thresholds: dict[str, int] = field(default_factory=dict)
    admin_broadcast_chats: list[str] = field(default_factory=list)
    # 0 = 用旧 cron 定时（times + weekdays_only）；>0 = 事件驱动模式：
    # 每 N 分钟 refresh sheet，状态变化立即广播该项目（cron 不再触发）
    refresh_interval_minutes: int = 5
    # === 滞留阈值播报（status -> 滞留小时数；超过这个时间在内部群提醒）===
    stuck_status_hours: dict[str, int] = field(default_factory=dict)
    # 例：{"MAKING": 24, "CLIENT_REVIEW": 24, "WAITING_SUBMIT": 24}
    # 0 = 禁用该项检查
    # === 商店上架监测（SECOND_REVIEW） ===
    store_monitor_interval_minutes: int = 30   # 多长时间扫一次 SECOND_REVIEW 项目
    store_monitor_min_hours: int = 4           # 未上架时下次重试的最短间隔
    store_monitor_max_hours: int = 8           # 最长间隔
    store_monitor_proxy_url: str = ""          # 可选代理（留空=直连）


def load_scheduler_config(path: Path) -> BroadcastConfig:
    """读 config/scheduler.yaml，返回 BroadcastConfig。

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: times 格式错误 / 缺 broadcast 段
    """
    if not path.exists():
        raise FileNotFoundError(f"Scheduler config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    bc = raw.get("broadcast")
    if not isinstance(bc, dict):
        raise ValueError("scheduler.yaml missing 'broadcast:' section")

    times = bc.get("times") or ["09:00", "18:00"]
    if not isinstance(times, list) or not times:
        raise ValueError("broadcast.times must be a non-empty list")
    for t in times:
        if not isinstance(t, str) or not _HHMM_RE.match(t):
            raise ValueError(f"invalid time format: {t!r} (expected HH:MM)")

    return BroadcastConfig(
        times=list(times),
        weekdays_only=bool(bc.get("weekdays_only", True)),
        skip_if_no_change=bool(bc.get("skip_if_no_change", True)),
        per_status_thresholds=dict(bc.get("per_status_thresholds") or {}),
        admin_broadcast_chats=list(bc.get("admin_broadcast_chats") or []),
        refresh_interval_minutes=int(bc.get("refresh_interval_minutes", 5)),
        stuck_status_hours=dict(bc.get("stuck_status_hours") or {}),
        store_monitor_interval_minutes=int(bc.get("store_monitor_interval_minutes", 30)),
        store_monitor_min_hours=int(bc.get("store_monitor_min_hours", 4)),
        store_monitor_max_hours=int(bc.get("store_monitor_max_hours", 8)),
        store_monitor_proxy_url=str(bc.get("store_monitor_proxy_url") or ""),
    )
