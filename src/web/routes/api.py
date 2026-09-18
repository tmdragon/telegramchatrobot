"""JSON API 路由。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api")


class RefreshBody(BaseModel):
    spreadsheet_names: Optional[list[str]] = None


@router.get("/projects")
async def get_projects(request: Request):
    app = request.app
    cache = app.state.cache

    if cache is None or (cache.empty() and _store_empty(app)):
        raise HTTPException(
            status_code=503,
            detail="cold start failure: cache empty and no SQLite snapshot",
        )

    summaries = cache.list_summaries() if cache else []
    last = cache.last_refresh_at() if cache else None
    return {
        "last_refresh_at": last.isoformat() if last else None,
        "projects": [
            {
                "project_id": s.project_id,
                "project_name": s.project_name,
                "status": s.status.value if s.status else None,
                "dwell_seconds": s.dwell_seconds,
            }
            for s in summaries
        ],
        "error_count": cache.error_count() if cache else 0,
    }


@router.post("/refresh")
async def post_refresh(request: Request, body: Optional[RefreshBody] = None):
    app = request.app
    refresher = getattr(app.state, "refresher", None)
    if refresher is None:
        raise HTTPException(status_code=503, detail="refresher not initialized")
    result = await refresher.refresh_now(
        spreadsheet_names=(body.spreadsheet_names if body else None),
    )
    return result


def _store_empty(app) -> bool:
    """检查 Store 是否所有 spreadsheet 都无快照。"""
    store = app.state.store
    cfg = app.state.cfg
    for ss in cfg.spreadsheets:
        if store.load_latest_snapshot(ss.id, ss.name) is not None:
            return False
    return True


@router.get("/projects/{project_id}")
async def get_project_detail(request: Request, project_id: str):
    app = request.app
    cache = app.state.cache
    if cache is None:
        raise HTTPException(status_code=503, detail="cache not initialized")
    p = cache.get(project_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")

    from src.web.cache import LOCKED_RECOGNIZED_AS

    def field_payload(field, sheet_name):
        fid = f"{sheet_name}::{sheet_name}::{field.row_index}::{field.column_index}"
        editable = (field.recognized_as or "") not in LOCKED_RECOGNIZED_AS
        return {
            "field_id": fid,
            "name": field.name,
            "value": field.value,
            "recognized_as": field.recognized_as,
            "editable": editable,
        }

    last = cache.last_refresh_at()
    return {
        "project": {
            "project_id": p.project_id,
            "project_name": p.project_name,
            "status": p.status.value if p.status else None,
            "status_changed_at": p.status_changed_at.isoformat() if p.status_changed_at else None,
            "status_history": [
                {"status": s.value if hasattr(s, "value") else s, "at": t.isoformat()}
                for s, t in p.status_history
            ],
            "sheets": [
                {
                    "spreadsheet_name": sv.sheet_name,
                    "sheet_name": sv.sheet_name,
                    "fetched_at": sv.fetched_at.isoformat(),
                    "fields": [field_payload(f, sv.sheet_name) for f in sv.fields],
                }
                for sv in p.sheets
            ],
        },
        "last_refresh_at": last.isoformat() if last else None,
    }