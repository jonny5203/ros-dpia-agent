"""Shared pytest configuration."""

from __future__ import annotations

from unittest.mock import AsyncMock


def pytest_configure(config):
    """Register the `slow` marker so pytest doesn't warn about unknown marks.

    Slow tests need a live Qdrant (or Docling model load) and are skipped by
    `pytest -m "not slow"`. Fast tests run on every commit and every machine.
    """
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with -m 'not slow')"
    )


def pytest_sessionstart(session):
    """Patch arq.create_pool so lifespan doesn't try to connect to Redis.

    FastAPI's lifespan runs once when TestClient(app) enters its context. The
    real arq pool eagerly connects to Redis on construction, which would fail
    in test environments without Redis (or hang ~30s on timeouts). We swap the
    factory for one returning an AsyncMock so lifespan completes instantly
    and routes that need the pool get a mock via app.state.arq_pool.
    """
    from app.main import create_app  # noqa: F401  (ensures module import patches take)
    import app.main as main_module

    fake_pool = AsyncMock()
    fake_pool.close = AsyncMock()
    main_module.create_pool = AsyncMock(return_value=fake_pool)
