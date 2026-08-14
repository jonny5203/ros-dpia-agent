"""arq worker entrypoint: `arq app.workers.arq_app.WorkerSettings`.

The worker still boots and connects to Redis so the compose
stack is exercised end-to-end.
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.workers.jobs import analyze_project, ingest_document, run_dpia_screening


async def on_startup(ctx: dict[str, Any]) -> None:
    """Build heavy clients once per worker and share them with jobs through ``ctx``."""
    from qdrant_client import AsyncQdrantClient

    from app.ai.providers.openrouter import OpenRouterClient
    from app.services.storage import StorageService

    s = get_settings()
    ctx["openrouter"] = OpenRouterClient(s)
    ctx["qdrant"] = AsyncQdrantClient(url=s.qdrant_url)
    ctx["storage"] = StorageService(s)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await ctx["openrouter"].close()
    await ctx["qdrant"].close()


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    """arq discovers this class by name."""

    functions: ClassVar[list] = [
        ingest_document,
        analyze_project,
        run_dpia_screening,
    ]
    redis_settings = _redis_settings()
    max_jobs = 4
    job_timeout = 600
    on_startup = on_startup
    on_shutdown = on_shutdown
