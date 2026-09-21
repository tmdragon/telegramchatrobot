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
    )