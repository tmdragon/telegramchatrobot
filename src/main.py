"""应用入口（Phase 1）。

加载配置 → 初始化 SQLite → 拉一次所有 sheet → 打印摘要 → 退出。
后续 phase 在此基础上加 UI / Bot / Scheduler。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import load_config
from src.sheets.auth import make_gspread_client
from src.sheets.repo import SheetRepo
from src.sheets.mapping_repo import MappingRepo
from src.store.db import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="checkGPRobot")
    parser.add_argument("--secrets", type=Path,
                        default=Path("config/secrets.yaml"))
    parser.add_argument("--sheets", type=Path,
                        default=Path("config/sheets.yaml"))
    parser.add_argument("--db", type=Path,
                        default=Path("data/checkgprobot.db"))
    args = parser.parse_args(argv)

    cfg = load_config(args.secrets, args.sheets)
    print(f"[config] {len(cfg.spreadsheets)} spreadsheets configured")

    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = Store(args.db)
    store.init_schema()
    print(f"[store] SQLite initialized at {args.db}")

    client = make_gspread_client(cfg.google_service_account_json)
    repo = SheetRepo(client)
    projects = repo.fetch_all(cfg.spreadsheets)
    print(f"[data] Loaded {len(projects)} projects")
    for p in projects:
        status = p.status.value if p.status else "UNKNOWN"
        print(f"  • {p.project_id} {p.project_name or ''} — {status}")

    # 持久化 sheet 快照（Phase 1 简化：把整个 Project 序列化为快照）
    from datetime import datetime, timezone
    fetched_at = datetime.now(timezone.utc)
    for ss in cfg.spreadsheets:
        try:
            sh = client.open(ss.name)
            ws = sh.worksheet(ss.name)
            rows = ws.get_all_values()
            store.save_sheet_snapshot(
                spreadsheet_id=ss.id,
                sheet_name=ss.name,
                fetched_at=fetched_at,
                rows_json=json.dumps(rows, ensure_ascii=False),
                parse_errors=None,
            )
        except Exception as e:
            print(f"[warn] failed to snapshot {ss.name}: {e}")

    # 加载并打印映射
    try:
        mapping_repo = MappingRepo(client)
        mappings = mapping_repo.load_all()
        for m in mappings:
            store.save_mapping_snapshot(m)
        print(f"[mapping] Loaded {len(mappings)} mappings")
    except Exception as e:
        print(f"[warn] mapping load skipped: {e}")

    return 0