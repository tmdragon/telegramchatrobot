from pathlib import Path
import pytest
from src.config import load_config, AppConfig

def test_load_config_returns_app_config(tmp_path: Path):
    secrets = tmp_path / "secrets.yaml"
    sheets = tmp_path / "sheets.yaml"
    secrets.write_text(
        "google_service_account_json: data/credentials/gcp-sa.json\n"
        "telegram_bot_token: '123:ABC'\n"
        "admin_chat_id: '12345'\n"
        "ui_port: 8765\n"
        "ui_bind: '127.0.0.1'\n",
        encoding="utf-8",
    )
    sheets.write_text(
        "spreadsheets:\n"
        "  - id: 'ss1'\n"
        "    name: '项目主表'\n"
        "    role: 'master'\n",
        encoding="utf-8",
    )
    cfg = load_config(secrets, sheets)
    assert isinstance(cfg, AppConfig)
    assert cfg.google_service_account_json == Path("data/credentials/gcp-sa.json")
    assert cfg.telegram_bot_token == "123:ABC"
    assert cfg.ui_port == 8765
    assert len(cfg.spreadsheets) == 1
    assert cfg.spreadsheets[0].id == "ss1"


def test_load_config_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml", tmp_path / "nope2.yaml")