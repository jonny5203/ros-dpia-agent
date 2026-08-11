"""Contract tests for versioned DPIA screening persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Screenings
from app.domain.dpia import evaluate_dpia_screening
from app.repositories.dpia import (
    InvalidDpiaRunTransition,
    ScreeningRepository,
)
from app.schemas.chunk import ChunkRef
from app.schemas.dpia import (
    DpiaEvidenceSnapshot,
    DpiaEvidenceSnapshotEntry,
    DpiaRunStatus,
    DpiaScreeningRunRead,
)
from app.schemas.screening import (
    Art35TriggerAssessment,
    Art35TriggerId,
    CriterionStatus,
    DpiaConclusion,
    DpiaCriterionAssessment,
    DpiaCriterionId,
    DpiaScreeningInput,
    DpiaScreeningResult,
)

PROJECT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_PROJECT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
DOCUMENT_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
CHUNK_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
USER_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


class FakeRows:
    def __init__(self, rows: list[Screenings]) -> None:
        self.rows = rows

    def scalars(self) -> FakeRows:
        return self

    def all(self) -> list[Screenings]:
        return self.rows


def _reference() -> ChunkRef:
    return ChunkRef(
        chunkId=CHUNK_ID,
        documentId=DOCUMENT_ID,
        documentName="Systembeskrivelse.pdf",
        page=1,
        sectionTitle="Overview",
    )


def _snapshot(
    project_id: UUID = PROJECT_ID,
) -> DpiaEvidenceSnapshot:
    return DpiaEvidenceSnapshot(
        project_id=project_id,
        retrieval_version="dpia-retrieval.v1",
        embedding_model="openai/text-embedding-3-large",
        embedding_dimensions=3072,
        queries=("DPIA query",),
        per_query_limit=8,
        evidence_limit=24,
        retrieved_at=NOW,
        evidence_text=('[C1] (Systembeskrivelse.pdf, p.1): "Evidence"'),
        entries=(
            DpiaEvidenceSnapshotEntry(
                token="C1",
                chunk_id=CHUNK_ID,
                document_id=DOCUMENT_ID,
                document_name="Systembeskrivelse.pdf",
                page=1,
                section_title="Overview",
                text="Evidence",
            ),
        ),
    )


def _result() -> DpiaScreeningResult:
    reference = _reference()
    screening = DpiaScreeningInput(
        criteria=[
            DpiaCriterionAssessment(
                id=criterion_id,
                status=CriterionStatus.NOT_TRIGGERED,
                rationale="Explicit negative evidence.",
                sourceReferences=[reference],
            )
            for criterion_id in DpiaCriterionId
        ],
        art35_3=[
            Art35TriggerAssessment(
                id=trigger_id,
                status=CriterionStatus.NOT_TRIGGERED,
                rationale="Explicit negative evidence.",
                sourceReferences=[reference],
            )
            for trigger_id in Art35TriggerId
        ],
    )
    return evaluate_dpia_screening(screening)


def _run(
    *,
    status: DpiaRunStatus = DpiaRunStatus.PENDING,
) -> Screenings:
    return Screenings(
        id=uuid4(),
        project_id=PROJECT_ID,
        requested_by=USER_ID,
        version=1,
        status=status.value,
        rules_version="dpia-rules.v1",
        created_at=NOW,
        updated_at=NOW,
    )


def _read_payload(
    *,
    status: DpiaRunStatus,
) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "requested_by": USER_ID,
        "version": 1,
        "status": status,
        "evidence_snapshot": None,
        "result": None,
        "conclusion": None,
        "model": None,
        "prompt_version": None,
        "rules_version": "dpia-rules.v1",
        "error": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def test_screenings_metadata_enforces_ownership_and_versions() -> None:
    table = cast(Table, Screenings.__table__)
    constraint_names = {
        constraint.name for constraint in table.constraints if constraint.name is not None
    }

    assert table.name == "screenings"
    assert {
        "ck_screenings_positive_version",
        "ck_screenings_status",
        "ck_screenings_rules_version",
        "ck_screenings_lifecycle",
        "uq_screenings_project_version",
    } <= constraint_names

    project_foreign_key = next(iter(table.c.project_id.foreign_keys))
    requester_foreign_key = next(iter(table.c.requested_by.foreign_keys))

    assert project_foreign_key.target_fullname == "projects.id"
    assert project_foreign_key.ondelete == "CASCADE"
    assert requester_foreign_key.target_fullname == "users.id"
    assert requester_foreign_key.ondelete == "SET NULL"
    assert table.c.requested_by.nullable is True


def test_ready_run_parses_json_into_typed_contracts() -> None:
    snapshot = _snapshot()
    result = _result()
    payload = _read_payload(status=DpiaRunStatus.READY_FOR_REVIEW)
    payload.update(
        {
            "evidence_snapshot": snapshot.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "conclusion": result.conclusion.value,
            "model": "model-v1",
            "prompt_version": "dpia-prompt.v1",
        }
    )

    run = DpiaScreeningRunRead.model_validate(payload)

    assert isinstance(
        run.evidence_snapshot,
        DpiaEvidenceSnapshot,
    )
    assert isinstance(run.result, DpiaScreeningResult)
    assert run.conclusion is DpiaConclusion.NOT_INDICATED


@pytest.mark.parametrize(
    ("status", "updates", "message"),
    [
        (
            DpiaRunStatus.PENDING,
            {"evidence_snapshot": _snapshot()},
            "pending screening",
        ),
        (
            DpiaRunStatus.RUNNING,
            {
                "result": _result(),
                "conclusion": DpiaConclusion.NOT_INDICATED,
            },
            "running screening",
        ),
        (
            DpiaRunStatus.READY_FOR_REVIEW,
            {
                "result": _result(),
                "conclusion": DpiaConclusion.NOT_INDICATED,
                "model": "model-v1",
                "prompt_version": "dpia-prompt.v1",
            },
            "ready screening",
        ),
        (
            DpiaRunStatus.FAILED,
            {"error": "   "},
            "nonblank error",
        ),
    ],
)
def test_run_schema_rejects_invalid_lifecycle(
    status: DpiaRunStatus,
    updates: dict[str, Any],
    message: str,
) -> None:
    payload = _read_payload(status=status)
    payload.update(updates)

    with pytest.raises(ValidationError, match=message):
        DpiaScreeningRunRead.model_validate(payload)


def test_run_schema_rejects_snapshot_from_another_project() -> None:
    payload = _read_payload(status=DpiaRunStatus.RUNNING)
    payload["evidence_snapshot"] = _snapshot(OTHER_PROJECT_ID)

    with pytest.raises(
        ValidationError,
        match="screening project",
    ):
        DpiaScreeningRunRead.model_validate(payload)


def test_run_schema_rejects_conclusion_mismatch() -> None:
    result = _result()
    payload = _read_payload(status=DpiaRunStatus.READY_FOR_REVIEW)
    payload.update(
        {
            "evidence_snapshot": _snapshot(),
            "result": result,
            "conclusion": DpiaConclusion.REQUIRED,
            "model": "model-v1",
            "prompt_version": "dpia-prompt.v1",
        }
    )

    with pytest.raises(
        ValidationError,
        match="must match",
    ):
        DpiaScreeningRunRead.model_validate(payload)


@pytest.mark.asyncio
async def test_create_pending_locks_project_before_allocating_version() -> None:
    raw_session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[PROJECT_ID, 4]),
        execute=AsyncMock(),
        add=Mock(),
        flush=AsyncMock(),
    )
    repository = ScreeningRepository(cast(AsyncSession, raw_session))

    run = await repository.create_pending(
        project_id=PROJECT_ID,
        rules_version=" dpia-rules.v1 ",
        requested_by=USER_ID,
    )

    assert raw_session.scalar.await_count == 2
    project_lock = raw_session.scalar.await_args_list[0].args[0]
    version_query = raw_session.scalar.await_args_list[1].args[0]

    assert "FOR UPDATE" in str(project_lock)
    assert "max(screenings.version)" in str(version_query)
    assert run.project_id == PROJECT_ID
    assert run.version == 4
    assert run.status == DpiaRunStatus.PENDING.value
    assert run.rules_version == "dpia-rules.v1"
    raw_session.add.assert_called_once_with(run)
    raw_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_repository_completes_run_without_accepting_conclusion() -> None:
    raw_session = SimpleNamespace(flush=AsyncMock())
    repository = ScreeningRepository(cast(AsyncSession, raw_session))
    run = _run()

    await repository.mark_running(run)
    await repository.store_snapshot(run, _snapshot())
    result = _result()
    await repository.complete(
        run,
        result=result,
        model=" model-v1 ",
        prompt_version=" dpia-prompt.v1 ",
    )

    assert run.status == DpiaRunStatus.READY_FOR_REVIEW.value
    assert run.evidence_snapshot == _snapshot().model_dump(mode="json")
    assert run.result == result.model_dump(mode="json")
    assert run.conclusion == result.conclusion.value
    assert run.model == "model-v1"
    assert run.prompt_version == "dpia-prompt.v1"
    assert raw_session.flush.await_count == 3

    read = DpiaScreeningRunRead.model_validate(run)
    assert read.conclusion is result.conclusion


@pytest.mark.asyncio
async def test_repository_rejects_snapshot_overwrite() -> None:
    raw_session = SimpleNamespace(flush=AsyncMock())
    repository = ScreeningRepository(cast(AsyncSession, raw_session))
    run = _run(status=DpiaRunStatus.RUNNING)
    run.evidence_snapshot = _snapshot().model_dump(mode="json")

    with pytest.raises(
        InvalidDpiaRunTransition,
        match="immutable",
    ):
        await repository.store_snapshot(run, _snapshot())


@pytest.mark.asyncio
async def test_failure_preserves_captured_snapshot() -> None:
    raw_session = SimpleNamespace(flush=AsyncMock())
    repository = ScreeningRepository(cast(AsyncSession, raw_session))
    snapshot_json = _snapshot().model_dump(mode="json")
    run = _run(status=DpiaRunStatus.RUNNING)
    run.evidence_snapshot = snapshot_json

    await repository.fail(
        run,
        error="  Model provider unavailable  ",
    )

    assert run.status == DpiaRunStatus.FAILED.value
    assert run.evidence_snapshot == snapshot_json
    assert run.error == "Model provider unavailable"
    assert run.result is None
    assert run.conclusion is None


@pytest.mark.asyncio
async def test_list_for_project_is_scoped_and_newest_first() -> None:
    rows = [
        _run(status=DpiaRunStatus.READY_FOR_REVIEW),
        _run(status=DpiaRunStatus.FAILED),
    ]
    raw_session = SimpleNamespace(execute=AsyncMock(return_value=FakeRows(rows)))
    repository = ScreeningRepository(cast(AsyncSession, raw_session))

    result = await repository.list_for_project(PROJECT_ID)

    assert result == rows
    statement = raw_session.execute.await_args.args[0]
    rendered = str(statement)
    assert "screenings.project_id" in rendered
    assert "ORDER BY screenings.version DESC" in rendered
