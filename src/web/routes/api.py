"""JSON API 路由。"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.models.project import Mapping as MappingModel
from src.models.status import normalize as normalize_status
from src.sheets.repo import WriteVerificationError
from src.web.cache import LOCKED_RECOGNIZED_AS

_CHAT_ID_RE = re.compile(r"^-?\d+$")

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
                "package_name": s.package_name,
                "status": s.status.value if s.status else None,
                "dwell_seconds": s.dwell_seconds,
                "payment_status": s.payment_status.value if s.payment_status else None,
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
    broadcast_svc = getattr(app.state, "broadcast_svc", None)

    result = await refresher.refresh_now(
        spreadsheet_names=(body.spreadsheet_names if body else None),
    )

    # 手动刷新也算事件驱动：检测到状态变化 → 立即播报该变化的项目
    # 与 _refresh_and_broadcast_wrapper 行为对齐（auto refresh 也会播）
    changes = result.get("changes", []) or []
    broadcast_count = 0
    if broadcast_svc is not None:
        for project in changes:
            try:
                await broadcast_svc.broadcast_project(project)
                broadcast_count += 1
            except Exception:  # noqa: BLE001
                # 单项目失败不影响整体
                pass

    result["broadcast_count"] = broadcast_count
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


@router.post("/projects/{project_id}/check-store")
async def post_check_store(request: Request, project_id: str):
    """手动触发单个项目的商店上架检查（忽略时间间隔，立刻查）。"""
    app = request.app
    refresher = getattr(app.state, "refresher", None)
    broadcast_svc = getattr(app.state, "broadcast_svc", None)
    scheduler_cfg = getattr(app.state, "scheduler_cfg", None)
    if refresher is None or broadcast_svc is None or scheduler_cfg is None:
        raise HTTPException(status_code=503, detail="store monitor not initialized")
    from src.scheduler.jobs import trigger_store_check_now
    result = await trigger_store_check_now(
        refresher, broadcast_svc, scheduler_cfg, project_id
    )
    if not result.get("ok"):
        reason = result.get("reason", "unknown")
        status = 404 if reason == "not_found" else 400
        raise HTTPException(status_code=status, detail=reason)
    return result


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


@router.get("/mappings")
async def get_mappings(request: Request):
    """返回所有映射。同步 IO 走 asyncio.to_thread。"""
    app = request.app
    mapping_repo = app.state.mapping_repo
    try:
        items = await asyncio.to_thread(mapping_repo.load_all)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"mapping load failed: {e}")
    return {
        "mappings": [
            {
                "project_id": m.project_id,
                "chat_id": m.chat_id,
                "note": m.note,
                "enabled": m.enabled,
                "last_broadcast_at": m.last_broadcast_at.isoformat() if m.last_broadcast_at else None,
                "last_broadcast_status": m.last_broadcast_status,
                "last_error": m.last_error,
            }
            for m in items
        ]
    }


class MappingCreateBody(BaseModel):
    project_id: str
    chat_id: str
    note: str = ""
    enabled: bool = True


class MappingUpdateBody(BaseModel):
    chat_id: str | None = None
    note: str | None = None
    enabled: bool | None = None


@router.post("/mappings", status_code=201)
async def post_mapping(request: Request, body: MappingCreateBody):
    app = request.app
    mapping_repo = app.state.mapping_repo
    store = app.state.store

    project_id = (body.project_id or "").strip()
    chat_id = (body.chat_id or "").strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    if not _CHAT_ID_RE.match(chat_id):
        raise HTTPException(status_code=400, detail="chat_id must be signed integer (e.g. -100...)")

    # 查重
    try:
        existing = await asyncio.to_thread(mapping_repo.load_all)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"mapping load failed: {e}")
    if any(m.project_id == project_id for m in existing):
        raise HTTPException(status_code=400, detail=f"mapping for {project_id} already exists (duplicate)")

    mapping = MappingModel(
        project_id=project_id, chat_id=chat_id, note=body.note, enabled=body.enabled,
        last_broadcast_at=None, last_broadcast_status=None, last_error=None,
    )
    try:
        await asyncio.to_thread(mapping_repo.upsert, mapping)
        await asyncio.to_thread(store.save_mapping_snapshot, mapping)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"write failed: {e}")
    return {
        "project_id": mapping.project_id,
        "chat_id": mapping.chat_id,
        "note": mapping.note,
        "enabled": mapping.enabled,
    }


@router.put("/mappings/{project_id}")
async def put_mapping(request: Request, project_id: str, body: MappingUpdateBody):
    app = request.app
    mapping_repo = app.state.mapping_repo
    store = app.state.store

    try:
        existing_list = await asyncio.to_thread(mapping_repo.load_all)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"mapping load failed: {e}")
    existing = next((m for m in existing_list if m.project_id == project_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"mapping {project_id} not found")

    updated = MappingModel(
        project_id=existing.project_id,
        chat_id=(body.chat_id if body.chat_id is not None else existing.chat_id),
        note=(body.note if body.note is not None else existing.note),
        enabled=(body.enabled if body.enabled is not None else existing.enabled),
        last_broadcast_at=existing.last_broadcast_at,  # 保留
        last_broadcast_status=existing.last_broadcast_status,
        last_error=existing.last_error,
    )
    if updated.chat_id and not _CHAT_ID_RE.match(updated.chat_id):
        raise HTTPException(status_code=400, detail="chat_id must be signed integer")
    try:
        await asyncio.to_thread(mapping_repo.upsert, updated)
        await asyncio.to_thread(store.save_mapping_snapshot, updated)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"write failed: {e}")
    return {
        "project_id": updated.project_id,
        "chat_id": updated.chat_id,
        "note": updated.note,
        "enabled": updated.enabled,
        "last_broadcast_at": updated.last_broadcast_at.isoformat() if updated.last_broadcast_at else None,
    }


@router.delete("/mappings/{project_id}")
async def delete_mapping(request: Request, project_id: str):
    """软删除：Phase 1 MappingRepo.delete 设置 enabled=FALSE。"""
    app = request.app
    mapping_repo = app.state.mapping_repo
    store = app.state.store
    try:
        await asyncio.to_thread(mapping_repo.delete, project_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"delete failed: {e}")
    # 同步本地 SQLite 快照（保 enabled=FALSE）
    try:
        existing_list = await asyncio.to_thread(mapping_repo.load_all)
    except Exception:  # noqa: BLE001
        existing_list = []
    existing = next((m for m in existing_list if m.project_id == project_id), None)
    if existing is not None:
        await asyncio.to_thread(store.save_mapping_snapshot, existing)
    return {
        "project_id": project_id,
        "enabled": False,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/mappings/{project_id}/test-send")
async def post_test_send(request: Request, project_id: str):
    """立即渲染文案并发送给该项目的映射 chat（用于 UI "测试发送"按钮）。

    503 bot_service 未配置；404 mapping 不存在 / project 不在 cache；
    502 Telegram API 失败；200 成功。
    """
    app = request.app
    bot_service = app.state.bot_service
    if bot_service is None:
        raise HTTPException(status_code=503, detail="Telegram bot not configured")

    # 解析 mapping（同步 gspread → to_thread）
    mapping_repo = app.state.mapping_repo
    try:
        mappings = await asyncio.to_thread(mapping_repo.load_all)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"mapping load failed: {e}")
    mapping = next((m for m in mappings if m.project_id == project_id), None)
    if mapping is None:
        raise HTTPException(status_code=404, detail=f"mapping for {project_id} not found")

    # 读 project
    cache = app.state.cache
    project = cache.get(project_id) if cache else None
    if project is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not in cache")

    # 读 chat_id override
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    chat_id = body.get("chat_id") or mapping.chat_id
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id not specified")

    from src.bot.templates import render_broadcast

    now = datetime.now(timezone.utc)
    text = render_broadcast(project, mapping, now, exceeded_threshold=False)

    try:
        await bot_service.send_message(chat_id, text)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"telegram send failed: {e}")

    return {
        "ok": True,
        "chat_id": chat_id,
        "message_preview": text,
    }