from pathlib import Path
from unittest.mock import patch, MagicMock
from src.sheets.auth import make_gspread_client


def test_make_gspread_client_loads_credentials(tmp_path: Path):
    fake_creds = tmp_path / "creds.json"
    fake_creds.write_text("{}", encoding="utf-8")

    with patch("src.sheets.auth.Credentials") as mock_creds_cls:
        mock_creds_cls.from_service_account_file.return_value = "FAKE_CREDS"
        with patch("src.sheets.auth.gspread.authorize") as mock_auth:
            mock_auth.return_value = "FAKE_CLIENT"
            client = make_gspread_client(fake_creds)

    mock_creds_cls.from_service_account_file.assert_called_once()
    args, kwargs = mock_creds_cls.from_service_account_file.call_args
    assert args[0].endswith("creds.json")
    assert "scopes" in kwargs
    mock_auth.assert_called_once_with("FAKE_CREDS")
    assert client == "FAKE_CLIENT"