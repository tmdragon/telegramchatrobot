"""页面路由（HTML）。"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.models.project import Field, Project, SheetView
from src.bot import templates as bot_templates

router = APIRouter()


def _hydrate_from_store(store, cfg) -> list[Project]:
    """冷启动：从 SQLite 快照反序列化出 Project 列表。

    每个 spreadsheet 一行快照；HeaderDetector 反推字段位置。
    若 cfg.spreadsheets 为空或 Store 无快照，返回空列表。
    """
    from src.sheets.parser import (
        HeaderDetector,
        PROJECT_ID_CANDIDATES,
        PROJECT_NAME_CANDIDATES,
        STATUS_CANDIDATES,
        parse_project_id,
        parse_status,
    )

    projects: dict[str, Project] = {}
    for ss in cfg.spreadsheets:
        snap = store.load_latest_snapshot(ss.id, ss.name)
        if snap is None:
            continue
        fetched_at, rows_json, _ = snap
        rows = json.loads(rows_json)
        if not rows:
            continue
        headers = rows[0]
        detector = HeaderDetector(headers)
        pid_col = detector.find_column(PROJECT_ID_CANDIDATES)
        if pid_col is None:
            continue
        status_col = detector.find_column(STATUS_CANDIDATES)
        name_col = detector.find_column(PROJECT_NAME_CANDIDATES)

        for row_idx, row in enumerate(rows[1:], start=2):
            if len(row) < len(headers):
                row = row + [""] * (len(headers) - len(row))
            pid = parse_project_id(row[pid_col - 1] if pid_col <= len(row) else None)
            if not pid:
                continue
            fields: list[Field] = []
            for col_idx, (header, value) in enumerate(zip(headers, row), start=1):
                recognized = None
                if col_idx == pid_col:
                    recognized = "project_id"
                elif status_col is not None and col_idx == status_col:
                    recognized = "status"
                elif name_col is not None and col_idx == name_col:
                    recognized = "project_name"
                fields.append(Field(
                    name=header, value=value, column_index=col_idx,
                    row_index=row_idx, recognized_as=recognized,
                ))
            sv = SheetView(spreadsheet_id=ss.id, sheet_name=ss.name,
                           fields=fields, fetched_at=fetched_at)
            status = parse_status(row[status_col - 1]) if status_col and status_col <= len(row) else None
            name = (row[name_col - 1].strip() or None) if name_col and name_col <= len(row) else None

            if pid not in projects:
                projects[pid] = Project(
                    project_id=pid, project_name=name, status=status,
                    status_changed_at=fetched_at, sheets=[sv],
                )
            else:
                p = projects[pid]
                if name and not p.project_name:
                    p.project_name = name
                if status and p.status != status:
                    p.status = status
                    p.status_changed_at = fetched_at
                p.sheets.append(sv)
    return list(projects.values())


@router.get("/", response_class=HTMLResponse)
async def overview(request: Request):
    app = request.app
    cache = app.state.cache
    cfg = app.state.cfg
    store = app.state.store
    templates = app.state.templates

    summaries: list[Any] = []
    if cache is not None and not cache.empty():
        summaries = cache.list_summaries()
    else:
        # 冷启动：从 Store hydrate
        if cache is None:
            from src.web.cache import ProjectCache
            cache = ProjectCache()
            app.state.cache = cache
        projects = _hydrate_from_store(store, cfg)
        if projects:
            cache.replace(projects)
            summaries = cache.list_summaries()

    last_refresh = cache.last_refresh_at() if cache else None
    from src.bot import templates as bot_templates
    last_refresh_human = (
        last_refresh.astimezone(bot_templates.DISPLAY_TZ).strftime("%Y-%m-%d %H:%M:%S")
        if last_refresh else None
    )

    empty_state = (
        not summaries
    )
    error_banner_visible = empty_state  # cache 空 → 视为拉取失败

    return templates.TemplateResponse(
        request=request,
        name="overview.html",
        context={
            "page_name": "overview",
            "summaries": summaries,
            "last_refresh_at": last_refresh.isoformat() if last_refresh else None,
            "last_refresh_human": last_refresh_human,
            "errors": ["无法连接 Google Sheets，检查凭证"] if error_banner_visible else [],
        },
    )


@router.get("/project/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str):
    app = request.app
    cache = app.state.cache
    templates = app.state.templates

    p = cache.get(project_id) if cache else None
    if p is None:
        return templates.TemplateResponse(
            request=request, name="404.html",
            context={"page_name": "404", "project_id": project_id,
                     "last_refresh_at": None, "last_refresh_human": None,
                     "errors": []},
            status_code=404,
        )

    dwell = 0
    if p.status_changed_at:
        from datetime import datetime, timezone
        dwell = max(0, int((datetime.now(timezone.utc) - p.status_changed_at).total_seconds()))
    last = cache.last_refresh_at() if cache else None
    last_human = (
        last.astimezone(bot_templates.DISPLAY_TZ).strftime("%Y-%m-%d %H:%M:%S")
        if last else None
    )

    return templates.TemplateResponse(
        request=request, name="project_detail.html",
        context={
            "page_name": "detail",
            "project": p,
            "dwell_seconds": dwell,
            "last_refresh_at": last.isoformat() if last else None,
            "last_refresh_human": last_human,
            "errors": [],
        },
    )


@router.get("/mappings", response_class=HTMLResponse)
async def mappings(request: Request):
    app = request.app
    mapping_repo = app.state.mapping_repo
    templates = app.state.templates
    cache = app.state.cache

    # mapping_repo.load_all 是同步 gspread → to_thread
    try:
        mappings_list = await asyncio.to_thread(mapping_repo.load_all)
    except Exception as e:  # noqa: BLE001
        return templates.TemplateResponse(
            request=request, name="mappings.html",
            context={
                "page_name": "mappings", "mappings": [],
                "last_refresh_at": None, "last_refresh_human": None,
                "errors": [f"无法读取映射表: {type(e).__name__}: {e}"],
            },
            status_code=200,
        )

    last = cache.last_refresh_at() if cache else None
    last_human = (
        last.astimezone(bot_templates.DISPLAY_TZ).strftime("%Y-%m-%d %H:%M:%S")
        if last else None
    )
    return templates.TemplateResponse(
        request=request, name="mappings.html",
        context={
            "page_name": "mappings", "mappings": mappings_list,
            "last_refresh_at": last.isoformat() if last else None,
            "last_refresh_human": last_human, "errors": [],
        },
    )
