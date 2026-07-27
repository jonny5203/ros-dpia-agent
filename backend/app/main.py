"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import AsyncQdrantClient
from starlette.middleware.sessions import SessionMiddleware

from app.ai.providers.openrouter import OpenRouterClient
from app.api.v1 import admin, documents, health, ingest, projects
from app.auth.router import router as auth_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import engine
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings: Settings = get_settings()
    app.state.settings = settings
    app.state.openrouter = OpenRouterClient(settings)
    app.state.qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    app.state.storage = StorageService(settings)
    app.state.arq_pool = await create_pool(
        RedisSettings.from_dsn(settings.redis_url)
    )
    logger.info("Starting %s (env=%s)", settings.app_name, settings.env)
    if not settings.openrouter_api_key_value:
        logger.warning("OPENROUTER_API_KEY is not set — AI stages will fail until it is finally set.")
    try:
        yield
    finally:
        await app.state.openrouter.close()
        await engine.dispose()
        await app.state.qdrant.close()
        await app.state.arq_pool.close()
        logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("DEBUG" if settings.debug else "INFO")

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.app_secret_key.get_secret_value(),
        session_cookie="dpia_session",
        same_site="lax",
        https_only=False,
        max_age=14 * 24 * 3600,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(health.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(auth_router)
    return app


# uvicorn / gunicorn entrypoint
app = create_app()
