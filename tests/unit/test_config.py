from pathlib import Path
import pytest
from src.config import load_config, AppConfig

# ===== 既有:纯 YAML 加载 =====

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


# ===== 新增:环境变量 fallback =====

@pytest.fixture
def yaml_paths(tmp_path: Path):
    """写一份 secrets.yaml + sheets.yaml,作为 env var 测试的基线."""
    secrets = tmp_path / "secrets.yaml"
    sheets = tmp_path / "sheets.yaml"
    secrets.write_text(
        "google_service_account_json: data/credentials/gcp-sa.json\n"
        "telegram_bot_token: 'yaml-token'\n"
        "admin_chat_id: '111'\n"
        "ui_port: 8765\n"
        "ui_bind: '127.0.0.1'\n"
        "display_timezone: 'UTC'\n",
        encoding="utf-8",
    )
    sheets.write_text(
        "spreadsheets:\n"
        "  - id: 'ss1'\n"
        "    name: '项目主表'\n"
        "    role: 'master'\n",
        encoding="utf-8",
    )
    return secrets, sheets


def test_env_var_overrides_telegram_token(yaml_paths, monkeypatch):
    monkeypatch.setenv("CHECKGPROBOT_TELEGRAM_BOT_TOKEN", "env-token")
    cfg = load_config(*yaml_paths)
    assert cfg.telegram_bot_token == "env-token"


def test_env_var_overrides_admin_chat_id(yaml_paths, monkeypatch):
    monkeypatch.setenv("CHECKGPROBOT_ADMIN_CHAT_ID", "999")
    cfg = load_config(*yaml_paths)
    assert cfg.admin_chat_id == "999"


def test_env_var_overrides_google_sa_json_path(yaml_paths, monkeypatch):
    monkeypatch.setenv("CHECKGPROBOT_GOOGLE_SA_JSON", "/etc/checkgprobot/gcp-sa.json")
    cfg = load_config(*yaml_paths)
    assert cfg.google_service_account_json == Path("/etc/checkgprobot/gcp-sa.json")


def test_google_application_credentials_env_overrides_sa(yaml_paths, monkeypatch):
    """GOOGLE_APPLICATION_CREDENTIALS 是 Google SDK 标准变量,优先级最高."""
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/secrets/gsa.json")
    cfg = load_config(*yaml_paths)
    assert cfg.google_service_account_json == Path("/secrets/gsa.json")


def test_google_application_credentials_overrides_checkgprobot_var(yaml_paths, monkeypatch):
    """GOOGLE_APPLICATION_CREDENTIALS 优先于自定义 CHECKGPROBOT_* 变量."""
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/standard/path.json")
    monkeypatch.setenv("CHECKGPROBOT_GOOGLE_SA_JSON", "/custom/path.json")
    cfg = load_config(*yaml_paths)
    assert cfg.google_service_account_json == Path("/standard/path.json")


def test_env_var_overrides_ui_port(yaml_paths, monkeypatch):
    monkeypatch.setenv("CHECKGPROBOT_UI_PORT", "9000")
    cfg = load_config(*yaml_paths)
    assert cfg.ui_port == 9000


def test_env_var_overrides_ui_bind(yaml_paths, monkeypatch):
    monkeypatch.setenv("CHECKGPROBOT_UI_BIND", "0.0.0.0")
    cfg = load_config(*yaml_paths)
    assert cfg.ui_bind == "0.0.0.0"


def test_env_var_overrides_display_timezone(yaml_paths, monkeypatch):
    monkeypatch.setenv("CHECKGPROBOT_DISPLAY_TIMEZONE", "Asia/Shanghai")
    cfg = load_config(*yaml_paths)
    assert cfg.display_timezone == "Asia/Shanghai"


def test_missing_env_var_falls_back_to_yaml(yaml_paths, monkeypatch):
    """环境变量未设置时,使用 YAML 值."""
    for var in (
        "CHECKGPROBOT_TELEGRAM_BOT_TOKEN",
        "CHECKGPROBOT_ADMIN_CHAT_ID",
        "CHECKGPROBOT_GOOGLE_SA_JSON",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "CHECKGPROBOT_UI_PORT",
        "CHECKGPROBOT_UI_BIND",
        "CHECKGPROBOT_DISPLAY_TIMEZONE",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg = load_config(*yaml_paths)
    assert cfg.telegram_bot_token == "yaml-token"
    assert cfg.admin_chat_id == "111"
    assert cfg.google_service_account_json == Path("data/credentials/gcp-sa.json")
    assert cfg.ui_port == 8765
    assert cfg.ui_bind == "127.0.0.1"
    assert cfg.display_timezone == "UTC"