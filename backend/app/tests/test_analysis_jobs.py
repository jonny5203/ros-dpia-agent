from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.analysis as analysis_service_module
import app.workers.jobs as worker_jobs
from app.ai.agents.extract_profile import NoEvidenceError
from app.services.analysis import AnalysisEnqueueError, AnalysisService


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeJobRepository:
    def __init__(self, job: SimpleNamespace) -> None:
        self.job = job
        self.updates: list[dict[str, object]] = []

    async def create_job(
        self,
        *,
        project_id: UUID,
        kind: str,
        arq_job_id: str | None = None,
    ) -> SimpleNamespace:
        self.job.project_id = project_id
        self.job.kind = kind
        self.job.arq_job_id = arq_job_id
        return self.job

    async def get_job(self, job_id: UUID) -> SimpleNamespace | None:
        return self.job if job_id == self.job.id else None

    async def update(
        self,
        job: SimpleNamespace,
        **fields: object,
    ) -> SimpleNamespace:
        self.updates.append(fields)
        for key, value in fields.items():
            setattr(job, key, value)
        return job


class FakePool:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def enqueue_job(self, function: str, **kwargs: Any) -> SimpleNamespace:
        self.calls.append((function, kwargs))
        if self.failure is not None:
            raise self.failure
        return SimpleNamespace(job_id="arq-123")


def _job(*, project_id: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        kind=None,
        status="queued",
        progress_pct=0,
        error=None,
        arq_job_id=None,
    )


@pytest.mark.asyncio
async def test_enqueue_persists_job_before_queueing(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()
    job = _job()
    repository = FakeJobRepository(job)
    session = FakeSession()
    pool = FakePool()

    monkeypatch.setattr(
        analysis_service_module,
        "JobRepository",
        lambda _: repository,
    )

    result = await AnalysisService(cast(AsyncSession, session)).enqueue(
        project_id=project_id,
        arq_pool=pool,  # type: ignore[arg-type]
        output_language="en",
    )

    assert result == job.id
    assert session.commits == 2
    assert pool.calls == [
        (
            "analyze_project",
            {
                "job_id": str(job.id),
                "project_id": str(project_id),
                "output_language": "en",
            },
        )
    ]
    assert repository.updates == [{"arq_job_id": "arq-123"}]


@pytest.mark.asyncio
async def test_enqueue_failure_is_pollable(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()
    job = _job()
    repository = FakeJobRepository(job)
    session = FakeSession()

    monkeypatch.setattr(
        analysis_service_module,
        "JobRepository",
        lambda _: repository,
    )

    with pytest.raises(AnalysisEnqueueError, match="could not be queued"):
        await AnalysisService(cast(AsyncSession, session)).enqueue(
            project_id=project_id,
            arq_pool=FakePool(failure=ConnectionError("redis unavailable")),  # type: ignore[arg-type]
        )

    assert session.commits == 2
    assert session.rollbacks == 1
    assert job.status == "failed"
    assert job.error == "Analysis could not be queued"


@pytest.mark.asyncio
async def test_analysis_worker_commits_profile_and_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    job = _job(project_id=project_id)
    repository = FakeJobRepository(job)
    session = FakeSession()
    captured: dict[str, object] = {}

    async def fake_extract_profile(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(worker_jobs, "SessionLocal", lambda: session)
    monkeypatch.setattr(worker_jobs, "get_settings", lambda: SimpleNamespace(llm_model="model-v1"))
    monkeypatch.setattr(worker_jobs, "extract_profile", fake_extract_profile)
    monkeypatch.setattr("app.repositories.job.JobRepository", lambda _: repository)

    await worker_jobs.analyze_project(
        {"openrouter": object(), "qdrant": object()},
        job_id=str(job.id),
        project_id=str(project_id),
        output_language="en",
    )

    assert repository.updates == [
        {"status": "running", "progress_pct": 10, "error": None},
        {"status": "complete", "progress_pct": 100, "error": None},
    ]
    assert session.commits == 2
    assert session.rollbacks == 0
    assert captured["project_id"] == project_id
    assert captured["model"] == "model-v1"
    assert captured["output_language"] == "en"


@pytest.mark.asyncio
async def test_analysis_worker_rolls_back_profile_before_failure_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    job = _job(project_id=project_id)
    repository = FakeJobRepository(job)
    session = FakeSession()

    async def fail_extraction(**kwargs: object) -> object:
        raise NoEvidenceError("project has no indexed evidence")

    monkeypatch.setattr(worker_jobs, "SessionLocal", lambda: session)
    monkeypatch.setattr(worker_jobs, "get_settings", lambda: SimpleNamespace(llm_model="model-v1"))
    monkeypatch.setattr(worker_jobs, "extract_profile", fail_extraction)
    monkeypatch.setattr("app.repositories.job.JobRepository", lambda _: repository)

    with pytest.raises(NoEvidenceError, match="no indexed evidence"):
        await worker_jobs.analyze_project(
            {"openrouter": object(), "qdrant": object()},
            job_id=str(job.id),
            project_id=str(project_id),
        )

    assert session.rollbacks == 1
    assert session.commits == 2
    assert repository.updates == [
        {"status": "running", "progress_pct": 10, "error": None},
        {"status": "failed", "error": "project has no indexed evidence"},
    ]
