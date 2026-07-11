# dpia-ros-backend

FastAPI backend for the Kommune DPIA & ROS Copilot. See the root `README.md`
and `IMPLEMENTATION_PLAN.md` for the full picture.

## Run (in the compose stack)

```bash
make up          # from repo root
make api-sh      # shell into the running api container
```

## Run locally (without Docker)

```bash
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload --port 8000
uv run pytest -q
uv run ruff check . && uv run mypy app
```

## Layout

```
app/
  main.py            # create_app() factory
  core/              # config (pydantic-settings), logging, exceptions (RFC 9457)
  api/v1/            # routers (Phase 0: /api/health)
  ai/providers/      # OpenRouter client (chat + embeddings) — Phase 0: wired + reachable
  workers/           # arq worker entrypoint
  tests/
```

Phase 1+ fills in `db/`, `domain/`, `schemas/`, `repositories/`, `services/`,
and the rest of `ai/` (embeddings, retrieval, prompts, agents, orchestrator).
