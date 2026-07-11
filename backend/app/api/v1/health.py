"""Health endpoint: confirms the app booted and that OpenRouter (chat +
embeddings) is reachable + key-valid. Always returns 200 so the container
healthcheck passes; `status` reports `degraded` if the sub-checks fail.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from app.ai.providers.openrouter import OpenRouterClient
from app.api.deps import get_openrouter

router = APIRouter(tags=["health"])

APP_VERSION = "0.1.0"


@router.get("/health")
async def health(client: OpenRouterClient = Depends(get_openrouter)) -> dict:
    started = time.monotonic()
    or_status = await client.reachability()
    elapsed_ms = round((time.monotonic() - started) * 1000, 1)

    key_bad = or_status.get("key_configured") and or_status.get("key_valid") is False
    degraded = (not or_status.get("reachable")) or bool(key_bad)

    return {
        "status": "degraded" if degraded else "ok",
        "app": "dpia-ros-backend",
        "version": APP_VERSION,
        "openrouter_ms": elapsed_ms,
        "openrouter": or_status,
    }
