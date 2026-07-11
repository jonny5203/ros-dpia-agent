"""arq worker entrypoint: `arq app.workers.arq_app.WorkerSettings`.

Phase 0: no jobs registered yet (document ingestion + the 5-step AI pipeline
land in Phase 3+). The worker still boots and connects to Redis so the compose
stack is exercised end-to-end.
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings


async def noop(_ctx: dict[str, Any]) -> None:
    """Placeholder job so the worker boots and connects to Redis.

    arq refuses to start without at least one registered function; real jobs
    (ingest_document, run_pipeline, ...) replace this in Phase 3+.
    """
    return None


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    """arq discovers this class by name."""

    functions: ClassVar[list] = [noop]  # Phase 3+: ingest_document, run_pipeline, ...
    redis_settings = _redis_settings()
    max_jobs = 4
    job_timeout = 600
