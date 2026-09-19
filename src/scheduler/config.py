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
    )
