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
