"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.ai.providers.openrouter import OpenRouterClient
from app.api.v1 import admin, health
from app.auth.router import router as auth_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    app.state.settings = settings
    app.state.openrouter = OpenRouterClient(settings)
    logger.info("Starting %s (env=%s)", settings.app_name, settings.env)
    if not settings.openrouter_api_key_value:
        logger.warning("OPENROUTER_API_KEY is not set — AI stages will fail until it is.")
    try:
        yield
    finally:
        await app.state.openrouter.aclose()
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
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.app_secret_key.get_secret_value(),
        session_cookie="dpia_session",
        same_site="lax",
        https_only=False,
        max_age=14 * 24 * 3600,
    )

    register_exception_handlers(app)
    app.include_router(health.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(auth_router)
    return app


# uvicorn / gunicorn entrypoint
app = create_app()
