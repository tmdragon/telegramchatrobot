"""FastAPI 应用工厂。

create_app() 接收 Phase 1+2 的 deps + Phase 3 的 bot_service / scheduler，
构造 FastAPI 实例，注册 Jinja2 环境（autoescape=True）、自定义过滤器、
`/health` 路由，并在 app.state 挂上所有依赖供后续路由访问。

Phase 3：增加 lifespan context manager，启动 BotService + Scheduler，
关闭时反向释放。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles
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
    scheduler: Optional[object] = None,
    admin_chat_id: Optional[int] = None,
) -> FastAPI:
    """构造并返回 FastAPI 应用实例。

    Args:
        bot_service: Phase 3 注入 BotService 实例；为 None 时 lifespan 跳过 bot 启动。
        scheduler: Phase 3 注入 AsyncIOScheduler 实例；为 None 时跳过。
        admin_chat_id: 管理员 Telegram user id（int）；为 None 时 bot 命令 admin gate 全放行。
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # === 启动 ===
        if bot_service is not None:
            await bot_service.start(cfg.telegram_bot_token)
            # 注册命令处理器
            from src.bot.commands import register_handlers

            cache = app.state.cache
            broadcast_svc = app.state.broadcast_svc
            store_ref = app.state.store
            register_handlers(
                bot_service._app,
                admin_chat_id=admin_chat_id or 0,
                cache=cache,
                broadcast_svc=broadcast_svc,
                bot_service=bot_service,
                store=store_ref,
            )
            bot_service._app.bot_data["mapping_repo"] = mapping_repo

        if scheduler is not None:
            scheduler.start()

        try:
            yield
        finally:
            # === 关闭 ===
            if scheduler is not None:
                try:
                    scheduler.shutdown(wait=False)
                except Exception:  # noqa: BLE001
                    pass
            if bot_service is not None:
                try:
                    await bot_service.stop()
                except Exception:  # noqa: BLE001
                    pass

    app = FastAPI(title="checkGPRobot UI", docs_url=None, redoc_url=None, lifespan=lifespan)

    # 挂依赖到 app.state 供路由访问
    app.state.cfg = cfg
    app.state.store = store
    app.state.sheet_repo = sheet_repo
    app.state.mapping_repo = mapping_repo
    app.state.bot_service = bot_service
    app.state.scheduler = scheduler
    app.state.admin_chat_id = admin_chat_id
    app.state.cache = None  # T3 注入 ProjectCache
    app.state.broadcast_svc = None  # Phase 3 注入 BroadcastSvc

    # Jinja2 环境（autoescape 默认 on：.html/.xml/.htm；这里强制 on 更稳）
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    templates.env.autoescape = True
    templates.env.filters["status_badge"] = status_badge
    templates.env.filters["humanize_duration"] = humanize_duration
    app.state.templates = templates

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # 路由（T3 注册 overview，T5 注册 project detail，T10a 注册 mappings）
    from src.web.routes import pages as pages_routes
    app.include_router(pages_routes.router)
    from src.web.routes import api as api_routes
    app.include_router(api_routes.router)

    # 静态资源（CSS / JS）—— T7a 完成
    app.mount("/static", StaticFiles(directory="src/web/static"), name="static")

    return app
