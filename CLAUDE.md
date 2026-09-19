# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`checkGPRobot` is a personal-use, local-only app: it reads multiple Google Sheets tracking project status, exposes them in a local web UI at `http://127.0.0.1:8765`, and broadcasts progress to Telegram groups via a long-polling bot. Single Python process runs FastAPI + Bot + APScheduler together. Spec: [docs/superpowers/specs/2026-09-18-checkgprobot-design.md](docs/superpowers/specs/2026-09-18-checkgprobot-design.md).

## Commands

```bash
# Install
pip install -r requirements.txt

# Configure (one-time)
cp config/secrets.yaml.example config/secrets.yaml
cp config/sheets.yaml.example config/sheets.yaml
# edit secrets.yaml: gcp-sa path, telegram token, admin chat_id
# edit sheets.yaml: list spreadsheet id/name/role

# Run
python run.py --secrets config/secrets.yaml --sheets config/sheets.yaml

# All tests
python -m pytest -v

# Single test
python -m pytest tests/test_bot_commands.py::test_status_cmd -v

# Single test file
python -m pytest tests/test_app_factory.py -v
```

Runtime data lives in `data/` (SQLite `data/checkgprobot.db`, SA credentials at `data/credentials/gcp-sa.json`) — both gitignored.

## Architecture

Single Python process, single event loop. uvicorn drives FastAPI; the bot and scheduler piggyback on the same loop. Synchronous gspread calls must be wrapped in `asyncio.to_thread(...)` — they would otherwise block the loop.

```
src/
├── main.py              # argparse + bootstrap; calls create_app() then uvicorn.run()
├── config.py            # AppConfig + SpreadsheetConfig from secrets.yaml + sheets.yaml
├── models/
│   ├── status.py        # StatusCode enum (14 states) + ALIASES table + LEGAL_TRANSITIONS + normalize()
│   └── project.py       # dataclasses: Project, Field, SheetView, Mapping
├── sheets/
│   ├── auth.py          # make_gspread_client(service-account-json)
│   ├── parser.py        # HeaderDetector + parse_project_id/parse_status
│   ├── repo.py          # SheetRepo.fetch_all() (merges multi-sheet by project_id), update_cell() with write-verify
│   └── mapping_repo.py  # MappingRepo (project ↔ Telegram chat_id) with load_all/upsert/delete
├── store/db.py          # Store: SQLite, 4 tables (sheet_snapshots, mapping_snapshot, broadcast_log, status_history)
├── web/
│   ├── app.py           # create_app() factory; mounts deps on app.state
│   ├── cache.py         # ProjectCache (in-memory; uvicorn single-thread → no locks needed)
│   ├── refresher.py     # BackgroundRefresher (asyncio.to_thread wrapper)
│   ├── filters.py       # Jinja2 filters: status_badge, humanize_duration
│   ├── routes/          # pages.py (HTML) + api.py (JSON API + edits)
│   ├── templates/       # Jinja2 (base, overview, project_detail, mappings, 404, partials/)
│   └── static/          # css/app.css + js/ (api.js, auto-refresh.js, inline-edit.js, ...)
└── bot/
    ├── service.py       # BotService: python-telegram-bot Application wrapper (async start/stop/send_message)
    ├── commands.py      # /status /projects /help /force_broadcast /reload /dryrun handlers + register_handlers()
    └── templates.py     # render_broadcast() Markdown + STATUS_EMOJI/STATUS_DISPLAY_CN tables
```

## Key Conventions

- **Status machine** lives in `models/status.py`. `normalize(value)` handles free-text → `StatusCode` via the alias table (Chinese + English, case-insensitive). `is_legal(from, to)` enforces the transition graph. All state-driven UI/broadcast logic should funnel through these helpers rather than re-implementing alias matching.
- **Known fields** recognized in sheets: `project_id` (locked in child tables), `status`, `project_name`. All other columns are editable from the project detail page. `LOCKED_RECOGNIZED_AS = frozenset({"project_id"})` in `web/cache.py`.
- **bot_data injection pattern**: handlers pull deps (`cache`, `broadcast_svc`, `store`, `admin_chat_id`) from `context.bot_data`. `register_handlers(app, ...)` writes them at registration time. `mapping_repo` is injected separately by the lifespan before polling starts (see `commands.py` comment).
- **MarkdownV2** is the Telegram parse mode; `BotService.send_message` sets it. Watch for reserved chars (`_ * [ ] ( ) ~ \` > # + - = | { } . !`) when hand-crafting strings — `humanize_duration` output and status display names contain none by default.
- **Admin gate**: `update.effective_user.id == admin_chat_id` (`admin_chat_id` is `int` in `bot_data`, not the YAML string). Compare directly, don't string-match.
- **Time storage**: SQLite columns are `TEXT`, ISO8601 with timezone; `Store.log_broadcast`/etc. accept `datetime` and `.isoformat()` on the way in, `.fromisoformat()` on the way out. Always timezone-aware (`datetime.now(timezone.utc)`).
- **Single-file ≤200 lines** is a project rule — split if a module grows beyond that.
- **One commit per task** with `feat(phase<N>): <verb> <thing>` convention (visible in recent git log on `phase3-bot` branch).
- **`bot_service=None` is a valid state** for `create_app(...)` — `/api/mappings/{id}/test-send` returns 503 "Telegram bot not configured" when unset. Don't crash on `None`.

## Tests

- `tests/unit/` and `tests/integration/` mirror `src/` layout; root `tests/` holds API + smoke tests.
- Bot tests use `pytest-asyncio`; PTB handlers are exercised with `AsyncMock` and a fake `context.bot_data` dict.
- SQLite tests use `tmp_path` for an isolated `.db`; never write to `data/checkgprobot.db` from tests.
- `conftest.py` exposes only a `project_root` fixture — module-specific fixtures live next to the test file.

## Phase Status

Tracked in [README.md](README.md). Current branch `phase3-bot` has Phase 1 (data) and Phase 2 (FastUI) complete; Phase 3 (bot + scheduler) is in progress — `bot/service.py`, `bot/commands.py`, `bot/templates.py` landed; `bot/broadcast.py`, `bot/notifications.py`, `src/scheduler/`, and FastAPI lifespan wiring are the remaining pieces (see `docs/superpowers/plans/2026-09-18-checkgprobot-phase3-bot-scheduler.md`).
