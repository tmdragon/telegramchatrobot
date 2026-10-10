"""配置加载。

secrets.yaml: 敏感信息（不进 git）
sheets.yaml: 业务配置（公开）
环境变量: 在 systemd / Docker 部署时覆盖 YAML 中的敏感字段。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class SpreadsheetConfig:
    id: str
    name: str
    role: str


@dataclass
class AppConfig:
    google_service_account_json: Path
    telegram_bot_token: str
    admin_chat_id: str
    ui_port: int
    ui_bind: str
    spreadsheets: list[SpreadsheetConfig] = field(default_factory=list)
    # 播报 / UI 显示用的时区（IANA 名，如 "Asia/Shanghai"；默认 UTC）
    display_timezone: str = "UTC"
    # gp-packer-server 配置：env 优先，未配置时 token/base_url 为空,
    # main.py 检测到空 token 时不构造 GpPackerClient,路由层 503。
    gp_packer_token: str = ""
    gp_packer_base_url: str = "https://gp.theluckypatti.com"

    def get_spreadsheet_by_role(self, role: str) -> SpreadsheetConfig | None:
        """按 role 查 spreadsheet 配置;不存在返回 None。"""
        return next((s for s in self.spreadsheets if s.role == role), None)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _env(name: str) -> str | None:
    """返回去掉首尾空白的环境变量值;未设置或为空字符串时返回 None."""
    val = os.environ.get(name)
    if val is None:
        return None
    val = val.strip()
    return val if val else None


def write_scheduler_config(path: Path, cfg: BroadcastConfig) -> None:
    """把 BroadcastConfig 原子写到 scheduler.yaml(带 .bak 备份)。

    流程:
    1. 备份原文件(.bak)
    2. 序列化 cfg → dict → yaml
    3. 写入新文件
    4. 反序列化验证可读(yaml.safe_load 不抛错)
    """
    import shutil
    from io import StringIO
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    data = _broadcast_config_to_dict(cfg)
    buf = StringIO()
    yaml.safe_dump(data, buf, allow_unicode=True, sort_keys=False)
    path.write_text(buf.get_value(), encoding="utf-8")
    # 验证
    with path.open("r", encoding="utf-8") as f:
        yaml.safe_load(f)


def _broadcast_config_to_dict(cfg: BroadcastConfig) -> dict:
    """BroadcastConfig → dict(只持久化跟 broadcast 相关的字段)。"""
    return {
        "broadcast": {
            "times": list(cfg.times),
            "weekdays_only": cfg.weekdays_only,
            "skip_if_no_change": cfg.skip_if_no_change,
            "per_status_thresholds": dict(cfg.per_status_thresholds),
            "admin_broadcast_chats": list(cfg.admin_broadcast_chats),
            "refresh_interval_minutes": cfg.refresh_interval_minutes,
            "stuck_status_hours": dict(cfg.stuck_status_hours),
            "store_monitor_interval_minutes": cfg.store_monitor_interval_minutes,
            "store_monitor_min_hours": cfg.store_monitor_min_hours,
            "store_monitor_max_hours": cfg.store_monitor_max_hours,
            "store_monitor_proxy_url": cfg.store_monitor_proxy_url,
            "online_check_interval_hours": cfg.online_check_interval_hours,
            "online_check_max_attempts": cfg.online_check_max_attempts,
            "online_check_retry_interval_minutes": cfg.online_check_retry_interval_minutes,
            "online_check_proxy_api_url": cfg.online_check_proxy_api_url,
            "online_check_default_country": cfg.online_check_default_country,
        }
    }


def load_config(secrets_path: Path, sheets_path: Path) -> AppConfig:
    secrets = _read_yaml(secrets_path)
    sheets = _read_yaml(sheets_path)

    # 优先级: GOOGLE_APPLICATION_CREDENTIALS > CHECKGPROBOT_GOOGLE_SA_JSON > YAML
    sa_json = (
        _env("GOOGLE_APPLICATION_CREDENTIALS")
        or _env("CHECKGPROBOT_GOOGLE_SA_JSON")
        or secrets["google_service_account_json"]
    )

    return AppConfig(
        google_service_account_json=Path(sa_json),
        telegram_bot_token=(
            _env("CHECKGPROBOT_TELEGRAM_BOT_TOKEN")
            or secrets["telegram_bot_token"]
        ),
        admin_chat_id=str(
            _env("CHECKGPROBOT_ADMIN_CHAT_ID") or secrets["admin_chat_id"]
        ),
        ui_port=int(
            _env("CHECKGPROBOT_UI_PORT") or secrets.get("ui_port", 8765)
        ),
        ui_bind=(
            _env("CHECKGPROBOT_UI_BIND") or secrets.get("ui_bind", "127.0.0.1")
        ),
        spreadsheets=[
            SpreadsheetConfig(id=s["id"], name=s["name"], role=s["role"])
            for s in sheets.get("spreadsheets", [])
        ],
        display_timezone=(
            _env("CHECKGPROBOT_DISPLAY_TIMEZONE")
            or secrets.get("display_timezone", "UTC")
        ),
        # gp-packer:env 优先,secrets.yaml 兑底
        gp_packer_token=(
            _env("CHECKGPROBOT_GP_PACKER_TOKEN")
            or secrets.get("gp_packer_token", "")
        ),
        gp_packer_base_url=(
            _env("CHECKGPROBOT_GP_PACKER_BASE_URL")
            or secrets.get("gp_packer_base_url", "https://gp.theluckypatti.com")
        ),
    )