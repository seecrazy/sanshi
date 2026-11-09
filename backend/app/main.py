"""应用工厂：create_app() 组装 DB/Redis/Hub/路由/任务。"""
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.config import Settings
from app.core.cache import TieredCache
from app.core.errors import (
    BizError,
    NotFoundError,
    PermissionDeniedError,
    StateConflictError,
)
from app.core.metrics import MetricsMiddleware
from app.database import Database
from app.jobs import start_jobs
from app.services.outbox_service import AppContext
from app.ws.hub import Hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    tasks = []
    if settings.auto_create:
        await app.state.db.create_all()
    if settings.jobs_enabled:
        ctx = AppContext(
            session_factory=app.state.db.session_factory,
            redis=app.state.redis,
            hub=app.state.hub,
            settings=settings,
        )
        tasks = start_jobs(ctx)
    yield
    for t in tasks:
        t.cancel()
    await app.state.db.close()
    try:
        await app.state.redis.aclose()
    except Exception:
        pass


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="叁食 Sanshi API", version="0.1.0", lifespan=_lifespan)
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.hub = Hub()
    app.state.cache = TieredCache(
        app.state.redis, local_ttl=settings.cache_local_ttl
    )
    app.add_middleware(MetricsMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(BizError)
    async def biz_error_handler(request: Request, exc: BizError):
        if isinstance(exc, StateConflictError):
            status = 409
        elif isinstance(exc, PermissionDeniedError):
            status = 403
        elif isinstance(exc, NotFoundError):
            status = 404
        else:
            status = 400
        return JSONResponse({"detail": exc.message}, status_code=status)

    @app.get("/health", tags=["meta"])
    async def health():
        return {"ok": True, "service": "sanshi"}

    app.include_router(api_router)
    return app


app = create_app()
