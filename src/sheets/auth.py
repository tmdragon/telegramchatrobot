"""Google Sheets 认证。

使用服务账号 JSON（gcp-sa.json），返回 gspread.Client。
"""
from __future__ import annotations

from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials


# 需要的 OAuth scopes（只读 + 读写 sheet）
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def make_gspread_client(credentials_json_path: Path) -> gspread.Client:
    """从服务账号 JSON 创建 gspread client。"""
    creds = Credentials.from_service_account_file(
        str(credentials_json_path),
        scopes=SCOPES,
    )
    return gspread.authorize(creds)