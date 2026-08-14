"""Queue and worker tests for versioned DPIA screening runs."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.dpia_runs as dpia_run_service_module
import app.workers.jobs as worker_jobs
from app.ai.retrieval import NoRetrievedEvidenceError
from app.schemas.dpia import (
    DpiaEvidenceSnapshot,
    DpiaEvidenceSnapshotEntry,
    DpiaRunStatus,
)
from app.services.dpia_runs import (
    DPIA_JOB_KIND,
    DPIA_QUEUE_FAILURE_ERROR,
    DpiaRunEnqueueError,
    DpiaRunService,
)


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
        return self.job if self.job.id == job_id else None

    async def update(
        self,
        job: SimpleNamespace,
        **fields: object,
    ) -> SimpleNamespace:
        self.updates.append(fields)
        for name, value in fields.items():
            setattr(job, name, value)
        return job


class FakeScreeningRepository:
    def __init__(self, run: SimpleNamespace) -> None:
        self.run = run
        self.actions: list[str] = []

    async def create_pending(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        rules_version: str,
        requested_by: UUID | None,
    ) -> SimpleNamespace:
        self.run.project_id = project_id
        self.run.job_id = job_id
        self.run.rules_version = rules_version
        self.run.requested_by = requested_by
        self.run.status = DpiaRunStatus.PENDING.value
        self.actions.append("create_pending")
        return self.run

    async def get_for_project(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
    ) -> SimpleNamespace | None:
        if self.run.id == run_id and self.run.project_id == project_id:
            return self.run
        return None

    async def mark_running(
        self,
        run: SimpleNamespace,
    ) -> SimpleNamespace:
        run.status = DpiaRunStatus.RUNNING.value
        self.actions.append("mark_running")
        return run

    async def store_snapshot(
        self,
        run: SimpleNamespace,
        snapshot: DpiaEvidenceSnapshot,
    ) -> SimpleNamespace:
        run.evidence_snapshot = snapshot.model_dump(mode="json")
        self.actions.append("store_snapshot")
        return run

    async def complete(
        self,
        run: SimpleNamespace,
        *,
        result: object,
        model: str,
        prompt_version: str,
    ) -> SimpleNamespace:
        run.result = result
        run.conclusion = "DPIA_NOT_INDICATED"
        run.model = model
        run.prompt_version = prompt_version
        run.error = None
        run.status = DpiaRunStatus.READY_FOR_REVIEW.value
        self.actions.append("complete")
        return run

    async def fail(
        self,
        run: SimpleNamespace,
        *,
        error: str,
    ) -> SimpleNamespace:
        run.result = None
        run.conclusion = None
        run.model = None
        run.prompt_version = None
        run.error = error
        run.status = DpiaRunStatus.FAILED.value
        self.actions.append("fail")
        return run


class FakePool:
    def __init__(
        self,
        session: FakeSession,
        *,
        failure: Exception | None = None,
        reject: bool = False,
    ) -> None:
        self.session = session
        self.failure = failure
        self.reject = reject
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.commits_seen_at_enqueue: list[int] = []

    async def enqueue_job(
        self,
        function: str,
        **kwargs: Any,
    ) -> SimpleNamespace | None:
        self.calls.append((function, kwargs))
        self.commits_seen_at_enqueue.append(self.session.commits)

        if self.failure is not None:
            raise self.failure
        if self.reject:
            return None
        return SimpleNamespace(job_id="arq-dpia-123")


def _job(project_id: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        kind=None,
        status="queued",
        progress_pct=0,
        error=None,
        arq_job_id=None,
    )


def _run(
    project_id: UUID | None = None,
    job_id: UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        requested_by=None,
        job_id=job_id,
        version=3,
        status=DpiaRunStatus.PENDING.value,
        evidence_snapshot=None,
        result=None,
        conclusion=None,
        model=None,
        prompt_version=None,
        rules_version="dpia-rules.v1",
        error=None,
    )


def _snapshot(project_id: UUID) -> DpiaEvidenceSnapshot:
    return DpiaEvidenceSnapshot(
        project_id=project_id,
        retrieval_version="dpia-retrieval.v1",
        embedding_model="embedding-v1",
        embedding_dimensions=1024,
        queries=("DPIA evidence",),
        per_query_limit=8,
        evidence_limit=24,
        retrieved_at=datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        evidence_text='[C1] (System.pdf, p.1): "Evidence"',
        entries=(
            DpiaEvidenceSnapshotEntry(
                token="C1",
                chunk_id=uuid4(),
                document_id=uuid4(),
                document_name="System.pdf",
                page=1,
                section_title="Overview",
                text="Evidence",
            ),
        ),
    )


@pytest.mark.asyncio
async def test_enqueue_commits_linked_rows_before_queue_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    requested_by = uuid4()
    session = FakeSession()
    job = _job()
    run = _run()
    jobs = FakeJobRepository(job)
    screenings = FakeScreeningRepository(run)
    pool = FakePool(session)

    monkeypatch.setattr(
        dpia_run_service_module,
        "JobRepository",
        lambda _: jobs,
    )
    monkeypatch.setattr(
        dpia_run_service_module,
        "ScreeningRepository",
        lambda _: screenings,
    )

    response = await DpiaRunService(cast(AsyncSession, session)).enqueue_dpia_run(
        project_id=project_id,
        requested_by=requested_by,
        arq_pool=cast(ArqRedis, pool),
    )

    assert response.run_id == run.id
    assert response.job_id == job.id
    assert response.version == 3
    assert response.status == "pending"
    assert run.job_id == job.id
    assert run.requested_by == requested_by
    assert pool.commits_seen_at_enqueue == [1]
    assert pool.calls == [
        (
            DPIA_JOB_KIND,
            {
                "job_id": str(job.id),
                "run_id": str(run.id),
                "project_id": str(project_id),
            },
        )
    ]
    assert session.commits == 2
    assert jobs.updates == [{"arq_job_id": "arq-dpia-123"}]


@pytest.mark.asyncio
async def test_enqueue_failure_marks_both_persisted_records_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    session = FakeSession()
    job = _job()
    run = _run()
    jobs = FakeJobRepository(job)
    screenings = FakeScreeningRepository(run)

    monkeypatch.setattr(
        dpia_run_service_module,
        "JobRepository",
        lambda _: jobs,
    )
    monkeypatch.setattr(
        dpia_run_service_module,
        "ScreeningRepository",
        lambda _: screenings,
    )

    with pytest.raises(
        DpiaRunEnqueueError,
        match="could not be queued",
    ):
        await DpiaRunService(cast(AsyncSession, session)).enqueue_dpia_run(
            project_id=project_id,
            requested_by=uuid4(),
            arq_pool=cast(
                ArqRedis,
                FakePool(
                    session,
                    failure=ConnectionError("redis password was exposed"),
                ),
            ),
        )

    assert session.commits == 2
    assert session.rollbacks == 1
    assert run.version == 3
    assert run.status == DpiaRunStatus.FAILED.value
    assert run.error == DPIA_QUEUE_FAILURE_ERROR
    assert job.status == "failed"
    assert job.error == DPIA_QUEUE_FAILURE_ERROR
    assert "password" not in run.error


@pytest.mark.asyncio
async def test_worker_commits_snapshot_before_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    job = _job(project_id)
    job.kind = DPIA_JOB_KIND
    run = _run(project_id, job.id)
    session = FakeSession()
    jobs = FakeJobRepository(job)
    screenings = FakeScreeningRepository(run)
    snapshot = _snapshot(project_id)
    captured: dict[str, object] = {}

    async def fake_retrieve(**kwargs: object) -> SimpleNamespace:
        captured["retrieval"] = kwargs
        return SimpleNamespace(snapshot=snapshot)

    async def fake_extract(**kwargs: object) -> object:
        captured["extraction"] = kwargs
        captured["commits_before_extraction"] = session.commits
        return object()

    monkeypatch.setattr(worker_jobs, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        worker_jobs,
        "get_settings",
        lambda: SimpleNamespace(llm_model="dpia-model-v1"),
    )
    monkeypatch.setattr(
        worker_jobs,
        "retrieve_dpia_evidence",
        fake_retrieve,
    )
    monkeypatch.setattr(
        worker_jobs,
        "extract_dpia_screening",
        fake_extract,
    )
    monkeypatch.setattr(
        "app.repositories.job.JobRepository",
        lambda _: jobs,
    )
    monkeypatch.setattr(
        "app.repositories.dpia.ScreeningRepository",
        lambda _: screenings,
    )
    monkeypatch.setattr(
        "app.repositories.document.DocumentRepository",
        lambda _: object(),
    )

    client = object()
    await worker_jobs.run_dpia_screening(
        {
            "openrouter": client,
            "qdrant": object(),
        },
        job_id=str(job.id),
        run_id=str(run.id),
        project_id=str(project_id),
    )

    assert captured["commits_before_extraction"] == 2
    extraction = cast(dict[str, object], captured["extraction"])
    assert extraction["snapshot"] is snapshot
    assert extraction["model"] == "dpia-model-v1"
    assert extraction["client"] is client
    assert session.commits == 3
    assert session.rollbacks == 0
    assert run.status == DpiaRunStatus.READY_FOR_REVIEW.value
    assert run.evidence_snapshot == snapshot.model_dump(mode="json")
    assert job.status == "complete"
    assert job.progress_pct == 100
    assert screenings.actions == [
        "mark_running",
        "store_snapshot",
        "complete",
    ]


@pytest.mark.asyncio
async def test_worker_failure_preserves_snapshot_and_hides_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    job = _job(project_id)
    job.kind = DPIA_JOB_KIND
    run = _run(project_id, job.id)
    session = FakeSession()
    jobs = FakeJobRepository(job)
    screenings = FakeScreeningRepository(run)
    snapshot = _snapshot(project_id)

    async def fake_retrieve(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(snapshot=snapshot)

    async def fail_extraction(**kwargs: object) -> object:
        raise RuntimeError("provider secret and response body")

    monkeypatch.setattr(worker_jobs, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        worker_jobs,
        "get_settings",
        lambda: SimpleNamespace(llm_model="dpia-model-v1"),
    )
    monkeypatch.setattr(
        worker_jobs,
        "retrieve_dpia_evidence",
        fake_retrieve,
    )
    monkeypatch.setattr(
        worker_jobs,
        "extract_dpia_screening",
        fail_extraction,
    )
    monkeypatch.setattr(
        "app.repositories.job.JobRepository",
        lambda _: jobs,
    )
    monkeypatch.setattr(
        "app.repositories.dpia.ScreeningRepository",
        lambda _: screenings,
    )
    monkeypatch.setattr(
        "app.repositories.document.DocumentRepository",
        lambda _: object(),
    )

    with pytest.raises(RuntimeError, match="provider secret"):
        await worker_jobs.run_dpia_screening(
            {
                "openrouter": object(),
                "qdrant": object(),
            },
            job_id=str(job.id),
            run_id=str(run.id),
            project_id=str(project_id),
        )

    assert session.commits == 3
    assert session.rollbacks == 1
    assert run.status == DpiaRunStatus.FAILED.value
    assert run.evidence_snapshot == snapshot.model_dump(mode="json")
    assert run.error == "DPIA screening failed"
    assert job.status == "failed"
    assert job.error == "DPIA screening failed"
    assert "secret" not in run.error


@pytest.mark.asyncio
async def test_worker_records_specific_no_evidence_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    job = _job(project_id)
    job.kind = DPIA_JOB_KIND
    run = _run(project_id, job.id)
    session = FakeSession()
    jobs = FakeJobRepository(job)
    screenings = FakeScreeningRepository(run)

    async def fail_retrieval(**kwargs: object) -> object:
        raise NoRetrievedEvidenceError("internal retrieval details")

    monkeypatch.setattr(worker_jobs, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        worker_jobs,
        "get_settings",
        lambda: SimpleNamespace(llm_model="dpia-model-v1"),
    )
    monkeypatch.setattr(
        worker_jobs,
        "retrieve_dpia_evidence",
        fail_retrieval,
    )
    monkeypatch.setattr(
        "app.repositories.job.JobRepository",
        lambda _: jobs,
    )
    monkeypatch.setattr(
        "app.repositories.dpia.ScreeningRepository",
        lambda _: screenings,
    )
    monkeypatch.setattr(
        "app.repositories.document.DocumentRepository",
        lambda _: object(),
    )

    with pytest.raises(NoRetrievedEvidenceError):
        await worker_jobs.run_dpia_screening(
            {
                "openrouter": object(),
                "qdrant": object(),
            },
            job_id=str(job.id),
            run_id=str(run.id),
            project_id=str(project_id),
        )

    expected = "No indexed evidence is available for DPIA screening"
    assert run.status == DpiaRunStatus.FAILED.value
    assert run.evidence_snapshot is None
    assert run.error == expected
    assert job.error == expected


@pytest.mark.asyncio
async def test_worker_rejects_a_run_linked_to_another_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    job = _job(project_id)
    job.kind = DPIA_JOB_KIND
    run = _run(project_id, uuid4())
    session = FakeSession()
    jobs = FakeJobRepository(job)
    screenings = FakeScreeningRepository(run)

    monkeypatch.setattr(worker_jobs, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        worker_jobs,
        "get_settings",
        lambda: SimpleNamespace(llm_model="dpia-model-v1"),
    )
    monkeypatch.setattr(
        "app.repositories.job.JobRepository",
        lambda _: jobs,
    )
    monkeypatch.setattr(
        "app.repositories.dpia.ScreeningRepository",
        lambda _: screenings,
    )

    with pytest.raises(
        worker_jobs.DpiaRunJobError,
        match="do not match",
    ):
        await worker_jobs.run_dpia_screening(
            {
                "openrouter": object(),
                "qdrant": object(),
            },
            job_id=str(job.id),
            run_id=str(run.id),
            project_id=str(project_id),
        )

    assert session.commits == 0
    assert run.status == DpiaRunStatus.PENDING.value
    assert job.status == "queued"


def test_worker_settings_registers_dpia_screening() -> None:
    from app.workers.arq_app import WorkerSettings

    assert worker_jobs.run_dpia_screening in WorkerSettings.functions
