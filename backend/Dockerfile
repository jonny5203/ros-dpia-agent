# syntax=docker/dockerfile:1
# FastAPI + arq image (api & worker share this).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# curl is required for the container healthcheck; tini for clean signal handling.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tini \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies first (better layer caching).
COPY pyproject.toml README.md ./
RUN uv pip install --system .

# Application code.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

# Drop root.
RUN useradd --create-home --uid 1000 appuser \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# tini reaps zombie processes (arq workers / subprocesses).
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
