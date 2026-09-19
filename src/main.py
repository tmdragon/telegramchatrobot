"""应用入口（Phase 1 + Phase 2）。

加载配置 → 初始化 SQLite → 拉一次所有 sheet → 打印摘要 → 启动 FastAPI UI。
Phase 3+ 在此基础上加 Bot / Scheduler。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import uvicorn

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
    mapping_repo = MappingRepo(client)
    try:
        mappings = mapping_repo.load_all()
        for m in mappings:
            store.save_mapping_snapshot(m)
        print(f"[mapping] Loaded {len(mappings)} mappings")
    except Exception as e:
        print(f"[warn] mapping load skipped: {e}")

    # ========== Phase 2 + Phase 3: 启动 FastUI + Bot + Scheduler ==========
    # 把所有 deps 注入到 FastAPI app
    from src.web.app import create_app
    from src.web.cache import ProjectCache
    from src.web.refresher import BackgroundRefresher
    from src.bot.service import BotService
    from src.bot.broadcast import BroadcastSvc
    from src.scheduler.config import load_scheduler_config
    from src.scheduler.jobs import build_scheduler

    cache = ProjectCache()
    bot_service = BotService()
    scheduler_cfg_path = Path("config/scheduler.yaml")
    # 缺 scheduler.yaml 时回退默认配置（BroadcastConfig 自带 times/weekdays_only 默认）
    try:
        scheduler_cfg = load_scheduler_config(scheduler_cfg_path)
    except FileNotFoundError:
        from src.scheduler.config import BroadcastConfig
        scheduler_cfg = BroadcastConfig()
    broadcast_svc = BroadcastSvc(
        bot_service=bot_service,
        mapping_repo=mapping_repo,
        store=store,
        cache=cache,
        admin_chat_id=int(cfg.admin_chat_id),
        per_status_thresholds=scheduler_cfg.per_status_thresholds,
    )
    scheduler = build_scheduler(broadcast_svc, scheduler_cfg)

    app = create_app(
        cfg=cfg,
        store=store,
        sheet_repo=repo,
        mapping_repo=mapping_repo,
        bot_service=bot_service,
        scheduler=scheduler,
        admin_chat_id=int(cfg.admin_chat_id),
    )
    app.state.cache = cache
    app.state.broadcast_svc = broadcast_svc
    app.state.refresher = BackgroundRefresher(repo, mapping_repo, store, cfg, cache)

    print(f"[ui] Listening on http://{cfg.ui_bind}:{cfg.ui_port}")
    print(f"[bot] token={cfg.telegram_bot_token[:6]}... admin={cfg.admin_chat_id}")
    print(f"[scheduler] {len(scheduler_cfg.times)} cron jobs, weekdays_only={scheduler_cfg.weekdays_only}")

    # 单线程 uvicorn（避免 SQLite 并发问题；gspread 已通过 asyncio.to_thread 异步化）
    uvicorn.run(
        app,
        host=cfg.ui_bind,
        port=cfg.ui_port,
        log_level="info",
        access_log=False,
    )
    return 0