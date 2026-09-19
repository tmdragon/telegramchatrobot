"""scheduler 配置加载测试。"""
from pathlib import Path

import pytest

from src.scheduler.config import BroadcastConfig, load_scheduler_config


def test_load_scheduler_config_full(tmp_path: Path):
    p = tmp_path / "scheduler.yaml"
    p.write_text(
        "broadcast:\n"
        "  times: ['09:00', '18:00']\n"
        "  weekdays_only: true\n"
        "  skip_if_no_change: true\n"
        "  per_status_thresholds:\n"
        "    MAKING: 14\n"
        "    CLIENT_REVIEW: 7\n",
        encoding="utf-8",
    )
    cfg = load_scheduler_config(p)
    assert isinstance(cfg, BroadcastConfig)
    assert cfg.times == ["09:00", "18:00"]
    assert cfg.weekdays_only is True
    assert cfg.skip_if_no_change is True
    assert cfg.per_status_thresholds == {"MAKING": 14, "CLIENT_REVIEW": 7}


def test_load_scheduler_config_defaults(tmp_path: Path):
    p = tmp_path / "scheduler.yaml"
    p.write_text("broadcast:\n  times: ['10:00']\n", encoding="utf-8")
    cfg = load_scheduler_config(p)
    assert cfg.times == ["10:00"]
    assert cfg.weekdays_only is True  # 默认
    assert cfg.skip_if_no_change is True
    assert cfg.per_status_thresholds == {}


def test_load_scheduler_config_missing_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_scheduler_config(tmp_path / "nope.yaml")


def test_times_must_be_hhmm_format(tmp_path: Path):
    p = tmp_path / "scheduler.yaml"
    p.write_text("broadcast:\n  times: ['bad-time']\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_scheduler_config(p)


def test_admin_broadcast_chats_parsed(tmp_path: Path):
    p = tmp_path / "scheduler.yaml"
    p.write_text(
        "broadcast:\n"
        "  times: ['09:00']\n"
        "  admin_broadcast_chats:\n"
        "    - '-1001234567890'\n"
        "    - '-1009876543210'\n",
        encoding="utf-8",
    )
    cfg = load_scheduler_config(p)
    assert cfg.admin_broadcast_chats == ["-1001234567890", "-1009876543210"]


def test_admin_broadcast_chats_default_empty(tmp_path: Path):
    p = tmp_path / "scheduler.yaml"
    p.write_text("broadcast:\n  times: ['09:00']\n", encoding="utf-8")
    cfg = load_scheduler_config(p)
    assert cfg.admin_broadcast_chats == []


def test_refresh_interval_minutes_parsed(tmp_path: Path):
    p = tmp_path / "scheduler.yaml"
    p.write_text(
        "broadcast:\n"
        "  times: ['09:00']\n"
        "  refresh_interval_minutes: 2\n",
        encoding="utf-8",
    )
    cfg = load_scheduler_config(p)
    assert cfg.refresh_interval_minutes == 2


def test_refresh_interval_minutes_default(tmp_path: Path):
    """未配 refresh_interval_minutes 时默认 5（事件驱动模式）。"""
    p = tmp_path / "scheduler.yaml"
    p.write_text("broadcast:\n  times: ['09:00']\n", encoding="utf-8")
    cfg = load_scheduler_config(p)
    assert cfg.refresh_interval_minutes == 5


def test_refresh_interval_minutes_zero_means_legacy_cron(tmp_path: Path):
    p = tmp_path / "scheduler.yaml"
    p.write_text(
        "broadcast:\n"
        "  times: ['09:00']\n"
        "  refresh_interval_minutes: 0\n",
        encoding="utf-8",
    )
    cfg = load_scheduler_config(p)
    assert cfg.refresh_interval_minutes == 0
