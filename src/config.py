"""配置加载。

secrets.yaml: 敏感信息（不进 git）
sheets.yaml: 业务配置（公开）
"""
from __future__ import annotations

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


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(secrets_path: Path, sheets_path: Path) -> AppConfig:
    secrets = _read_yaml(secrets_path)
    sheets = _read_yaml(sheets_path)
    return AppConfig(
        google_service_account_json=Path(secrets["google_service_account_json"]),
        telegram_bot_token=secrets["telegram_bot_token"],
        admin_chat_id=str(secrets["admin_chat_id"]),
        ui_port=int(secrets.get("ui_port", 8765)),
        ui_bind=secrets.get("ui_bind", "127.0.0.1"),
        spreadsheets=[
            SpreadsheetConfig(id=s["id"], name=s["name"], role=s["role"])
            for s in sheets.get("spreadsheets", [])
        ],
    )