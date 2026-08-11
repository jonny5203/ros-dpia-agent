# Backend

The FastAPI backend owns authentication, project and document workflows,
background-job coordination, document ingestion, retrieval, citation
verification, and persisted analysis results. Uploaded sources and provenance
are shared; DPIA and ROS are separate assessment pipelines.

Read the root [`README.md`](../README.md) for the product overview,
architecture, complete startup instructions, current feature status, and usage
workflow. Read [`IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md) for the
planned DPIA, ROS, review, and export phases.

## Main entry points

```text
app/main.py                 FastAPI application factory and shared clients
app/auth/                   Keycloak/OIDC BFF login, session, JWT, and roles
app/api/deps.py             Authentication and project-scope dependencies
app/api/v1/                 Health, projects, documents, jobs, search, analysis
app/services/               Application use-case coordination
app/repositories/           PostgreSQL persistence
app/ingestion/              Parsers, PII scan, and deterministic chunking
app/ai/providers/           AI-provider abstraction and OpenRouter client
app/ai/store/               Qdrant retrieval and indexing
app/ai/agents/              Two-pass project-profile extraction
app/ai/citations/           Evidence rendering and deterministic citation gate
app/workers/                arq ingestion and analysis jobs
app/tests/                  Unit and focused integration tests
alembic/                    Database migrations
```

## Run inside the complete stack

From the repository root:

```bash
make k8s-up
make k8s-api-sh
make backend-test
make backend-lint
```

The API is available through nginx at <http://localhost:8081/api>. Interactive
OpenAPI documentation is at <http://localhost:8081/api/docs>.

## Run the backend locally

The local process still requires reachable PostgreSQL, Redis, Qdrant, MinIO,
Keycloak, and OpenRouter configuration.

```bash
cd backend
uv sync --extra dev
UV_CACHE_DIR=/tmp/ros-dpia-uv-cache uv run uvicorn app.main:app --reload --port 8000
```

Verify with:

```bash
UV_CACHE_DIR=/tmp/ros-dpia-uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/ros-dpia-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/ros-dpia-uv-cache uv run mypy app
```

## API groups implemented now

- `/auth/*`: login, callback, current user, and logout.
- `/api/health`: application and OpenRouter health.
- `/api/v1/projects`: project CRUD.
- `/api/v1/projects/{id}/documents`: document upload, list, and delete.
- `/api/v1/jobs/{id}`: ingestion and analysis job polling.
- `/api/v1/documents/{id}/acknowledge`: unblock a critical PII finding after
  explicit review.
- `/api/v1/projects/{id}/search`: project-scoped hybrid search.
- `/api/v1/projects/{id}/analyze`: queued project-profile extraction.
- `/api/v1/projects/{id}/profile`: latest persisted safe profile.
- `/api/v1/documents/{id}/chunks/{chunk_id}`: citation drill-down.

DPIA screening is in progress. ROS and report export are not available yet.

## Assessment boundary

- DPIA and ROS may retrieve from the same project index.
- Each run creates its own evidence snapshot and verifies its own claims.
- Each pipeline owns its jobs, records, rules, review state, and audit events.
- DPIA never reads a ROS score, and ROS never reads a DPIA conclusion.
- A combined report references reviewed results; it does not merge them.
