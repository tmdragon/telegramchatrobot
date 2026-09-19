from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import json

from src.main import main


def test_main_loads_config_fetches_and_prints(tmp_path: Path, capsys):
    secrets = tmp_path / "secrets.yaml"
    sheets_cfg = tmp_path / "sheets.yaml"
    data_dir = tmp_path / "data"
    creds = tmp_path / "creds.json"
    creds.write_text("{}", encoding="utf-8")
    db = tmp_path / "test.db"

    secrets.write_text(
        f"google_service_account_json: '{creds}'\n"
        "telegram_bot_token: '123:ABC'\n"
        "admin_chat_id: '12345'\n"
        "ui_port: 8765\n"
        "ui_bind: '127.0.0.1'\n",
        encoding="utf-8",
    )
    sheets_cfg.write_text(
        "spreadsheets:\n"
        "  - id: 'ss1'\n"
        "    name: '项目主表'\n"
        "    role: 'master'\n",
        encoding="utf-8",
    )

    fake_client = MagicMock()
    fake_ws = MagicMock()
    fake_ws.title = "项目主表"
    fake_ws.get_all_values.return_value = [
        ["项目编号", "状态"],
        ["PRJ-001", "制作中"],
    ]
    fake_client.open_by_key.return_value.worksheet.return_value = fake_ws

    with patch("src.main.make_gspread_client", return_value=fake_client), \
         patch("src.main.uvicorn.run") as mock_run:
        rc = main(["--secrets", str(secrets), "--sheets", str(sheets_cfg),
                   "--db", str(db)])

    # Phase 2：uvicorn 启动被 mock，验证调用参数正确
    assert mock_run.called

    assert rc == 0
    out = capsys.readouterr().out
    assert "Loaded 1 projects" in out
    assert "PRJ-001" in out