"""JSON API 路由。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.models.status import normalize as normalize_status
from src.sheets.repo import WriteVerificationError
from src.web.cache import LOCKED_RECOGNIZED_AS

router = APIRouter(prefix="/api")


class RefreshBody(BaseModel):
    spreadsheet_names: Optional[list[str]] = None


class FieldEditBody(BaseModel):
    new_value: str


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


@router.put("/projects/{project_id}/fields/{field_id}")
async def put_field(request: Request, project_id: str, field_id: str, body: FieldEditBody):
    """字段编辑流程：decode field_id → 校验 → asyncio.to_thread(update_cell) → 更新 cache。

    SheetRepo.update_cell 是同步阻塞 IO（gspread），必须 asyncio.to_thread 包到线程池，
    否则 uvicorn 单线程 loop 会被阻塞。
    """
    app = request.app
    cache = app.state.cache
    store = app.state.store
    sheet_repo = app.state.sheet_repo

    if cache is None or cache.empty():
        raise HTTPException(status_code=503, detail="cache empty")

    p = cache.get(project_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")

    # field_id 解码
    try:
        decoded = unquote(field_id)
        parts = decoded.split("::", 3)
        if len(parts) != 4:
            raise ValueError("invalid field_id segments")
        spreadsheet_name, sheet_name, row_s, col_s = parts
        row = int(row_s)
        col = int(col_s)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid field_id encoding")

    new_value = (body.new_value or "").strip()
    if not new_value:
        raise HTTPException(status_code=400, detail="new_value is empty")

    # 在当前快照中定位 field
    target_field = None
    for sv in p.sheets:
        if sv.sheet_name != sheet_name:
            continue
        for f in sv.fields:
            if f.row_index == row and f.column_index == col:
                target_field = f
                break
        if target_field:
            break
    if target_field is None:
        raise HTTPException(status_code=404, detail="field not in current snapshot")

    # locked guard
    if (target_field.recognized_as or "") in LOCKED_RECOGNIZED_AS:
        raise HTTPException(
            status_code=400,
            detail=f"field '{target_field.name}' is locked (recognized_as={target_field.recognized_as})",
        )

    # 写 Sheets（异步包装同步 IO）
    original_value = target_field.value
    try:
        verified = await asyncio.to_thread(
            sheet_repo.update_cell, spreadsheet_name, sheet_name, row, col, new_value,
        )
    except WriteVerificationError as e:
        # 409 回滚：返回原值让 UI 还原
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(e),
                "original_value": original_value,
                "field_id": field_id,
            },
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"transport error: {e}")

    # 更新 cache
    cache.update_field_value(project_id, spreadsheet_name, sheet_name, row, col, verified)

    # 若改的是状态列，记录到 status_history
    status_changed = False
    new_status_code = None
    if target_field.recognized_as == "status":
        new_status_code = normalize_status(verified)
        if new_status_code is not None and new_status_code != p.status:
            now = datetime.now(timezone.utc)
            store.record_status(project_id, new_status_code.value, now)
            p.status = new_status_code
            p.status_changed_at = now
            status_changed = True

    return {
        "field_id": field_id,
        "value": verified,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status_changed": status_changed,
        "new_status_code": new_status_code.value if new_status_code else None,
    }