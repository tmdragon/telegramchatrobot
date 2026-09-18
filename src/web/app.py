"""FastAPI 应用工厂。

create_app() 接收 Phase 1 的 deps + 可选 bot_service，构造 FastAPI 实例，
注册 Jinja2 环境（autoescape=True）、自定义过滤器、`/health` 路由，
并在 app.state 挂上所有依赖供后续路由访问。

后续 T7b 还会调 app.mount('/static', ...)；本任务只暴露骨架。
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.templating import Jinja2Templates

from src.config import AppConfig
from src.sheets.repo import SheetRepo
from src.sheets.mapping_repo import MappingRepo
from src.store.db import Store
from src.web.filters import humanize_duration, status_badge


TEMPLATES_DIR = "src/web/templates"


def create_app(
    cfg: AppConfig,
    store: Store,
    sheet_repo: SheetRepo,
    mapping_repo: MappingRepo,
    bot_service: Optional[object] = None,
) -> FastAPI:
    """构造并返回 FastAPI 应用实例。

    Args:
        bot_service: Phase 3 注入；Phase 2 始终传 None。
    """
    app = FastAPI(title="checkGPRobot UI", docs_url=None, redoc_url=None)

    # 挂依赖到 app.state 供路由访问
    app.state.cfg = cfg
    app.state.store = store
    app.state.sheet_repo = sheet_repo
    app.state.mapping_repo = mapping_repo
    app.state.bot_service = bot_service
    app.state.cache = None  # T3 注入 ProjectCache

    # Jinja2 环境（autoescape 默认 on：.html/.xml/.htm；这里强制 on 更稳）
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    templates.env.autoescape = True
    templates.env.filters["status_badge"] = status_badge
    templates.env.filters["humanize_duration"] = humanize_duration
    app.state.templates = templates

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return app