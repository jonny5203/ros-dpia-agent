"""Contract tests for cited DPIA extraction and run-local citation verification."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypeVar, cast
from uuid import UUID

import pytest
from pydantic import BaseModel, ValidationError

from app.ai.dpia.extraction import (
    CITATION_REVIEW_RATIONALE_NB,
    CitedArt35TriggerAssessment,
    CitedDpiaCriterionAssessment,
    CitedDpiaReference,
    CitedDpiaScreeningInput,
    extract_dpia_screening,
    verify_dpia_citations,
)
from app.ai.prompts.dpia import (
    DPIA_PROMPT_VERSION,
    dpia_screening_messages,
)
from app.domain.dpia import (
    DPIA_RULES_VERSION,
    evaluate_dpia_screening,
)
from app.schemas.dpia import (
    DpiaEvidenceSnapshot,
    DpiaEvidenceSnapshotEntry,
    DpiaRunStatus,
    DpiaScreeningRunRead,
)
from app.schemas.screening import (
    Art35TriggerId,
    CriterionStatus,
    DpiaConclusion,
    DpiaCriterionId,
)

ModelT = TypeVar("ModelT", bound=BaseModel)

PROJECT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_PROJECT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
DOCUMENT_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
OTHER_DOCUMENT_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
CHUNK_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
OTHER_CHUNK_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
RUN_ID = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _snapshot(
    *,
    project_id: UUID = PROJECT_ID,
    chunk_id: UUID = CHUNK_ID,
    document_id: UUID = DOCUMENT_ID,
    document_name: str = "Systembeskrivelse.pdf",
) -> DpiaEvidenceSnapshot:
    evidence = "Prosjektet behandler helseopplysninger i stor skala."

    return DpiaEvidenceSnapshot(
        project_id=project_id,
        retrieval_version="dpia-retrieval.v1",
        embedding_model="openai/text-embedding-3-large",
        embedding_dimensions=3072,
        queries=("DPIA query",),
        per_query_limit=8,
        evidence_limit=24,
        retrieved_at=NOW,
        evidence_text=f"[{CitedDpiaReference(citation='C1').citation}] "
        f'({document_name}, p.1): "{evidence}"',
        entries=(
            DpiaEvidenceSnapshotEntry(
                token="C1",
                chunk_id=chunk_id,
                document_id=document_id,
                document_name=document_name,
                page=1,
                section_title="Behandlingsomfang",
                text=evidence,
            ),
        ),
    )


def _cited_references(
    tokens: list[str],
) -> list[CitedDpiaReference]:
    return [CitedDpiaReference(citation=token) for token in tokens]


def _cited_screening(
    *,
    criteria_statuses: dict[DpiaCriterionId, CriterionStatus] | None = None,
    criterion_tokens: dict[DpiaCriterionId, list[str]] | None = None,
    art35_statuses: dict[Art35TriggerId, CriterionStatus] | None = None,
    art35_tokens: dict[Art35TriggerId, list[str]] | None = None,
) -> CitedDpiaScreeningInput:
    selected_criteria = criteria_statuses or {}
    selected_criterion_tokens = criterion_tokens or {}
    selected_art35 = art35_statuses or {}
    selected_art35_tokens = art35_tokens or {}

    criteria: list[CitedDpiaCriterionAssessment] = []
    for criterion_id in DpiaCriterionId:
        status = selected_criteria.get(
            criterion_id,
            CriterionStatus.NOT_TRIGGERED,
        )
        tokens = selected_criterion_tokens.get(criterion_id, ["C1"])
        criteria.append(
            CitedDpiaCriterionAssessment(
                id=criterion_id,
                status=status,
                rationale=f"Vurdering av {criterion_id.value}.",
                sourceReferences=_cited_references(tokens),
            )
        )

    art35_3: list[CitedArt35TriggerAssessment] = []
    for trigger_id in Art35TriggerId:
        status = selected_art35.get(
            trigger_id,
            CriterionStatus.NOT_TRIGGERED,
        )
        tokens = selected_art35_tokens.get(trigger_id, ["C1"])
        art35_3.append(
            CitedArt35TriggerAssessment(
                id=trigger_id,
                status=status,
                rationale=f"Vurdering av {trigger_id.value}.",
                sourceReferences=_cited_references(tokens),
            )
        )

    return CitedDpiaScreeningInput(
        criteria=criteria,
        art35_3=art35_3,
    )


class FakeStructuredClient:
    def __init__(
        self,
        response: CitedDpiaScreeningInput,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def structured_completion(
        self,
        messages: list[dict[str, str]],
        *,
        response_model: type[ModelT],
        model: str | None = None,
        max_retries: int = 2,
        **kwargs: Any,
    ) -> ModelT:
        self.calls.append(
            {
                "messages": messages,
                "response_model": response_model,
                "model": model,
                "max_retries": max_retries,
                "kwargs": kwargs,
            }
        )

        if self.error is not None:
            raise self.error
        if response_model is not CitedDpiaScreeningInput:
            raise AssertionError(f"unexpected response model: {response_model}")

        return cast(ModelT, self.response)


def test_prompt_uses_norwegian_conservative_evidence_rules() -> None:
    snapshot = _snapshot()

    messages = dpia_screening_messages(snapshot.evidence_text)

    assert DPIA_PROMPT_VERSION == "dpia-screening.v1"
    assert DPIA_RULES_VERSION == "dpia-rules.v1"
    assert [message["role"] for message in messages] == ["system", "user"]

    system_message = messages[0]["content"].lower()
    assert "norsk bokmål" in system_message
    assert "taushet" in system_message
    assert "insufficient_evidence" in system_message
    assert "not_triggered" in system_message
    assert "ikke beregn" in system_message

    user_message = messages[1]["content"]
    assert f"<evidence>\n{snapshot.evidence_text}\n</evidence>" in user_message


def test_prompt_rejects_blank_evidence() -> None:
    with pytest.raises(
        ValueError,
        match="nonblank evidence",
    ):
        dpia_screening_messages("   ")


def test_model_response_requires_complete_inventory() -> None:
    complete = _cited_screening()

    with pytest.raises(
        ValidationError,
        match="each DPIA criterion exactly once",
    ):
        CitedDpiaScreeningInput(
            criteria=complete.criteria[:-1],
            art35_3=complete.art35_3,
        )


def test_valid_token_becomes_snapshot_derived_chunk_reference() -> None:
    verified = verify_dpia_citations(
        _cited_screening(),
        _snapshot(),
    )

    assessment = next(item for item in verified.criteria if item.id is DpiaCriterionId.EVALUATION)
    reference = assessment.sourceReferences[0]

    assert assessment.status is CriterionStatus.NOT_TRIGGERED
    assert assessment.rejectedCitations == []
    assert reference.chunkId == CHUNK_ID
    assert reference.documentId == DOCUMENT_ID
    assert reference.documentName == "Systembeskrivelse.pdf"
    assert reference.page == 1
    assert reference.sectionTitle == "Behandlingsomfang"


@pytest.mark.parametrize(
    ("tokens", "expected_rejected"),
    [
        ([], []),
        (["C999"], ["C999"]),
        (["C1", "C999"], ["C999"]),
    ],
)
def test_missing_invalid_or_mixed_citations_fail_closed(
    tokens: list[str],
    expected_rejected: list[str],
) -> None:
    cited = _cited_screening(
        criteria_statuses={
            DpiaCriterionId.LARGE_SCALE: CriterionStatus.TRIGGERED,
        },
        criterion_tokens={
            DpiaCriterionId.LARGE_SCALE: tokens,
        },
    )

    verified = verify_dpia_citations(cited, _snapshot())
    assessment = next(item for item in verified.criteria if item.id is DpiaCriterionId.LARGE_SCALE)
    result = evaluate_dpia_screening(verified)

    assert assessment.status is CriterionStatus.INSUFFICIENT_EVIDENCE
    assert assessment.rationale == CITATION_REVIEW_RATIONALE_NB
    assert assessment.sourceReferences == []
    assert [rejected.citation for rejected in assessment.rejectedCitations] == expected_rejected
    assert result.criteria_count == 0
    assert result.evidence_incomplete is True
    assert result.conclusion is DpiaConclusion.LIKELY


def test_same_token_is_resolved_from_each_runs_own_snapshot() -> None:
    cited = _cited_screening()
    first = verify_dpia_citations(
        cited,
        _snapshot(),
    )
    second = verify_dpia_citations(
        cited,
        _snapshot(
            project_id=OTHER_PROJECT_ID,
            chunk_id=OTHER_CHUNK_ID,
            document_id=OTHER_DOCUMENT_ID,
            document_name="Annet-prosjekt.pdf",
        ),
    )

    first_reference = first.criteria[0].sourceReferences[0]
    second_reference = second.criteria[0].sourceReferences[0]

    assert first_reference.chunkId == CHUNK_ID
    assert first_reference.documentId == DOCUMENT_ID
    assert second_reference.chunkId == OTHER_CHUNK_ID
    assert second_reference.documentId == OTHER_DOCUMENT_ID
    assert second_reference.documentName == "Annet-prosjekt.pdf"


@pytest.mark.asyncio
async def test_extraction_calls_model_once_and_applies_deterministic_rules() -> None:
    snapshot = _snapshot()
    client = FakeStructuredClient(
        _cited_screening(
            criteria_statuses={
                DpiaCriterionId.SENSITIVE_DATA: CriterionStatus.TRIGGERED,
                DpiaCriterionId.LARGE_SCALE: CriterionStatus.TRIGGERED,
            }
        )
    )

    result = await extract_dpia_screening(
        snapshot=snapshot,
        model="anthropic/claude-sonnet-4.5",
        client=client,
    )

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["response_model"] is CitedDpiaScreeningInput
    assert call["model"] == "anthropic/claude-sonnet-4.5"
    assert call["max_retries"] == 2
    assert call["kwargs"] == {"temperature": 0}
    assert snapshot.evidence_text in call["messages"][1]["content"]

    assert result.criteria_count == 2
    assert result.art35_3_triggered is False
    assert result.conclusion is DpiaConclusion.REQUIRED
    assert result.requires_human_review is True


@pytest.mark.asyncio
async def test_provider_failure_returns_no_partial_result() -> None:
    client = FakeStructuredClient(
        _cited_screening(),
        error=RuntimeError("provider unavailable"),
    )

    with pytest.raises(
        RuntimeError,
        match="provider unavailable",
    ):
        await extract_dpia_screening(
            snapshot=_snapshot(),
            model="anthropic/claude-sonnet-4.5",
            client=client,
        )

    assert len(client.calls) == 1


def test_rejected_citation_survives_kernel_and_persisted_json_round_trip() -> None:
    snapshot = _snapshot()
    verified = verify_dpia_citations(
        _cited_screening(
            criteria_statuses={
                DpiaCriterionId.LARGE_SCALE: CriterionStatus.TRIGGERED,
            },
            criterion_tokens={
                DpiaCriterionId.LARGE_SCALE: ["C1", "C999"],
            },
        ),
        snapshot,
    )
    result = evaluate_dpia_screening(verified)
    dumped_result = result.model_dump(mode="json")

    stored_assessment = next(
        item
        for item in dumped_result["criteria"]
        if item["id"] == DpiaCriterionId.LARGE_SCALE.value
    )
    assert stored_assessment["sourceReferences"] == []
    assert stored_assessment["rejectedCitations"] == [
        {
            "citation": "C999",
            "reason": "not_in_snapshot",
        }
    ]

    run = DpiaScreeningRunRead.model_validate(
        {
            "id": RUN_ID,
            "project_id": PROJECT_ID,
            "requested_by": None,
            "version": 1,
            "status": DpiaRunStatus.READY_FOR_REVIEW,
            "evidence_snapshot": snapshot.model_dump(mode="json"),
            "result": dumped_result,
            "conclusion": result.conclusion.value,
            "model": "anthropic/claude-sonnet-4.5",
            "prompt_version": DPIA_PROMPT_VERSION,
            "rules_version": DPIA_RULES_VERSION,
            "error": None,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )

    assert run.result is not None
    round_tripped = next(
        item for item in run.result.criteria if item.id is DpiaCriterionId.LARGE_SCALE
    )
    assert round_tripped.status is CriterionStatus.INSUFFICIENT_EVIDENCE
    assert round_tripped.sourceReferences == []
    assert [item.citation for item in round_tripped.rejectedCitations] == ["C999"]
