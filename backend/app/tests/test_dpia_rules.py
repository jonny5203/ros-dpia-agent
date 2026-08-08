"""Contract tests for the deterministic DPIA rules engine."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.dpia import evaluate_dpia_screening
from app.schemas.chunk import ChunkRef
from app.schemas.screening import (
    Art35TriggerAssessment,
    Art35TriggerId,
    CriterionStatus,
    DpiaConclusion,
    DpiaCriterionAssessment,
    DpiaCriterionId,
    DpiaScreeningInput,
)

REFERENCE = ChunkRef(
    chunkId=UUID("00000000-0000-0000-0000-000000000001"),
    documentId=UUID("11111111-1111-1111-1111-111111111111"),
    documentName="Systembeskrivelse.pdf",
    page=1,
    sectionTitle="Behandlingsaktiviteter",
)


def _references(status: CriterionStatus) -> list[ChunkRef]:
    if status is CriterionStatus.INSUFFICIENT_EVIDENCE:
        return []
    return [REFERENCE.model_copy()]


def _criteria(
    overrides: dict[DpiaCriterionId, CriterionStatus] | None = None,
) -> list[DpiaCriterionAssessment]:
    selected = overrides or {}

    return [
        DpiaCriterionAssessment(
            id=criterion_id,
            status=status,
            rationale=f"Vurdering av {criterion_id.value}",
            sourceReferences=_references(status),
        )
        for criterion_id in DpiaCriterionId
        if (
            status := selected.get(
                criterion_id,
                CriterionStatus.NOT_TRIGGERED,
            )
        )
    ]


def _art35_triggers(
    overrides: dict[Art35TriggerId, CriterionStatus] | None = None,
) -> list[Art35TriggerAssessment]:
    selected = overrides or {}

    return [
        Art35TriggerAssessment(
            id=trigger_id,
            status=status,
            rationale=f"Vurdering av {trigger_id.value}",
            sourceReferences=_references(status),
        )
        for trigger_id in Art35TriggerId
        if (
            status := selected.get(
                trigger_id,
                CriterionStatus.NOT_TRIGGERED,
            )
        )
    ]


def _screening(
    *,
    criteria: dict[DpiaCriterionId, CriterionStatus] | None = None,
    art35_3: dict[Art35TriggerId, CriterionStatus] | None = None,
) -> DpiaScreeningInput:
    return DpiaScreeningInput(
        criteria=_criteria(criteria),
        art35_3=_art35_triggers(art35_3),
    )


def test_zero_explicit_criteria_is_not_indicated() -> None:
    result = evaluate_dpia_screening(_screening())

    assert result.criteria_count == 0
    assert result.art35_3_triggered is False
    assert result.conclusion is DpiaConclusion.NOT_INDICATED
    assert result.evidence_incomplete is False
    assert result.requires_human_review is True


def test_one_criterion_is_likely() -> None:
    result = evaluate_dpia_screening(
        _screening(
            criteria={
                DpiaCriterionId.SENSITIVE_DATA: CriterionStatus.TRIGGERED,
            }
        )
    )

    assert result.criteria_count == 1
    assert result.conclusion is DpiaConclusion.LIKELY


def test_two_criteria_are_required() -> None:
    result = evaluate_dpia_screening(
        _screening(
            criteria={
                DpiaCriterionId.SENSITIVE_DATA: CriterionStatus.TRIGGERED,
                DpiaCriterionId.NEW_TECHNOLOGY: CriterionStatus.TRIGGERED,
            }
        )
    )

    assert result.criteria_count == 2
    assert result.conclusion is DpiaConclusion.REQUIRED


@pytest.mark.parametrize("trigger_id", list(Art35TriggerId))
def test_each_article_35_trigger_is_required(
    trigger_id: Art35TriggerId,
) -> None:
    result = evaluate_dpia_screening(
        _screening(
            art35_3={
                trigger_id: CriterionStatus.TRIGGERED,
            }
        )
    )

    assert result.criteria_count == 0
    assert result.art35_3_triggered is True
    assert result.conclusion is DpiaConclusion.REQUIRED


def test_insufficient_evidence_is_likely_and_flagged() -> None:
    result = evaluate_dpia_screening(
        _screening(
            criteria={
                DpiaCriterionId.LARGE_SCALE: (CriterionStatus.INSUFFICIENT_EVIDENCE),
            }
        )
    )

    assert result.criteria_count == 0
    assert result.conclusion is DpiaConclusion.LIKELY
    assert result.evidence_incomplete is True
    assert result.requires_human_review is True


def test_decisive_assessment_requires_verified_citation() -> None:
    with pytest.raises(
        ValidationError,
        match="decisive assessments require at least one verified citation",
    ):
        DpiaCriterionAssessment(
            id=DpiaCriterionId.SYSTEMATIC_MONITORING,
            status=CriterionStatus.TRIGGERED,
            rationale="Systematisk monitorering er dokumentert.",
            sourceReferences=[],
        )


def test_screening_requires_every_criterion_exactly_once() -> None:
    with pytest.raises(
        ValidationError,
        match="criteria must contain each DPIA criterion exactly once",
    ):
        DpiaScreeningInput(
            criteria=_criteria()[:-1],
            art35_3=_art35_triggers(),
        )


def test_result_uses_canonical_order_and_labels() -> None:
    screening = DpiaScreeningInput(
        criteria=list(reversed(_criteria())),
        art35_3=list(reversed(_art35_triggers())),
    )

    result = evaluate_dpia_screening(screening)

    assert [item.id for item in result.criteria] == list(DpiaCriterionId)
    assert [item.id for item in result.art35_3] == list(Art35TriggerId)
    assert result.criteria[0].label_nb == "Evaluering eller poengsetting"
