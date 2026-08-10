"""Cited DPIA extraction and run-local citation verification."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.prompts.dpia import dpia_screening_messages
from app.ai.providers.base import StructuredChatClient
from app.domain.dpia import evaluate_dpia_screening
from app.schemas.chunk import ChunkRef
from app.schemas.dpia import DpiaEvidenceSnapshot
from app.schemas.screening import (
    Art35TriggerAssessment,
    Art35TriggerId,
    CriterionStatus,
    DpiaCriterionAssessment,
    DpiaCriterionId,
    DpiaScreeningInput,
    DpiaScreeningResult,
    RejectedCitation,
)

CITATION_REVIEW_RATIONALE_NB = (
    "Vurderingen kunne ikke bekreftes mot bevisgrunnlaget for denne "
    "DPIA-kjøringen og må vurderes manuelt."
)


class CitedDpiaReference(BaseModel):
    """One model-facing citation token; UUID provenance is resolved later."""

    model_config = ConfigDict(extra="forbid")

    citation: str = Field(
        pattern=r"^C[1-9][0-9]*$",
        max_length=32,
    )


class _CitedEvidenceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CriterionStatus
    rationale: str = Field(min_length=1)
    sourceReferences: list[CitedDpiaReference] = Field(default_factory=list)


class CitedDpiaCriterionAssessment(_CitedEvidenceAssessment):
    id: DpiaCriterionId


class CitedArt35TriggerAssessment(_CitedEvidenceAssessment):
    id: Art35TriggerId


class CitedDpiaScreeningInput(BaseModel):
    """Stores all 9+3 model assessments before C1 labels become ChunkRef objects."""

    model_config = ConfigDict(extra="forbid")

    criteria: list[CitedDpiaCriterionAssessment]
    art35_3: list[CitedArt35TriggerAssessment]

    @model_validator(mode="after")
    def require_complete_inventories(self) -> Self:
        criterion_ids = [assessment.id for assessment in self.criteria]
        expected_criteria = set(DpiaCriterionId)

        if len(criterion_ids) != len(expected_criteria) or set(criterion_ids) != expected_criteria:
            raise ValueError("criteria must contain each DPIA criterion exactly once")

        trigger_ids = [assessment.id for assessment in self.art35_3]
        expected_triggers = set(Art35TriggerId)

        if len(trigger_ids) != len(expected_triggers) or set(trigger_ids) != expected_triggers:
            raise ValueError("art35_3 must contain each Article 35(3) trigger exactly once")

        return self


def _snapshot_reference_map(
    snapshot: DpiaEvidenceSnapshot,
) -> dict[str, ChunkRef]:
    """Build trusted references exclusively from this run's frozen snapshot."""

    return {
        entry.token: ChunkRef(
            chunkId=entry.chunk_id,
            documentId=entry.document_id,
            documentName=entry.document_name,
            page=entry.page,
            sectionTitle=entry.section_title,
        )
        for entry in snapshot.entries
    }


def _resolve_references(
    references: list[CitedDpiaReference],
    snapshot_references: dict[str, ChunkRef],
) -> tuple[list[ChunkRef], list[RejectedCitation]]:
    """Resolve unique tokens in model order and record tokens absent from the snapshot."""

    verified: list[ChunkRef] = []
    rejected: list[RejectedCitation] = []
    seen: set[str] = set()

    for reference in references:
        token = reference.citation
        if token in seen:
            continue
        seen.add(token)

        resolved = snapshot_references.get(token)
        if resolved is None:
            rejected.append(RejectedCitation(citation=token))
        else:
            verified.append(resolved)

    return verified, rejected


def _verify_criterion(
    assessment: CitedDpiaCriterionAssessment,
    snapshot_references: dict[str, ChunkRef],
) -> DpiaCriterionAssessment:
    verified, rejected = _resolve_references(
        assessment.sourceReferences,
        snapshot_references,
    )

    if assessment.status is CriterionStatus.INSUFFICIENT_EVIDENCE:
        return DpiaCriterionAssessment(
            id=assessment.id,
            status=CriterionStatus.INSUFFICIENT_EVIDENCE,
            rationale=assessment.rationale,
            sourceReferences=[],
            rejectedCitations=rejected,
        )

    if not verified or rejected:
        return DpiaCriterionAssessment(
            id=assessment.id,
            status=CriterionStatus.INSUFFICIENT_EVIDENCE,
            rationale=CITATION_REVIEW_RATIONALE_NB,
            sourceReferences=[],
            rejectedCitations=rejected,
        )

    return DpiaCriterionAssessment(
        id=assessment.id,
        status=assessment.status,
        rationale=assessment.rationale,
        sourceReferences=verified,
        rejectedCitations=[],
    )


def _verify_art35_trigger(
    assessment: CitedArt35TriggerAssessment,
    snapshot_references: dict[str, ChunkRef],
) -> Art35TriggerAssessment:
    verified, rejected = _resolve_references(
        assessment.sourceReferences,
        snapshot_references,
    )

    if assessment.status is CriterionStatus.INSUFFICIENT_EVIDENCE:
        return Art35TriggerAssessment(
            id=assessment.id,
            status=CriterionStatus.INSUFFICIENT_EVIDENCE,
            rationale=assessment.rationale,
            sourceReferences=[],
            rejectedCitations=rejected,
        )

    if not verified or rejected:
        return Art35TriggerAssessment(
            id=assessment.id,
            status=CriterionStatus.INSUFFICIENT_EVIDENCE,
            rationale=CITATION_REVIEW_RATIONALE_NB,
            sourceReferences=[],
            rejectedCitations=rejected,
        )

    return Art35TriggerAssessment(
        id=assessment.id,
        status=assessment.status,
        rationale=assessment.rationale,
        sourceReferences=verified,
        rejectedCitations=[],
    )


def verify_dpia_citations(
    cited: CitedDpiaScreeningInput,
    snapshot: DpiaEvidenceSnapshot,
) -> DpiaScreeningInput:
    """Resolve model token against one snapshot without making semantic judgements."""

    snapshot_references = _snapshot_reference_map(snapshot)

    return DpiaScreeningInput(
        criteria=[
            _verify_criterion(assessment, snapshot_references) for assessment in cited.criteria
        ],
        art35_3=[
            _verify_art35_trigger(assessment, snapshot_references) for assessment in cited.art35_3
        ],
    )


async def extract_dpia_screening(
    *,
    snapshot: DpiaEvidenceSnapshot,
    model: str,
    client: StructuredChatClient,
) -> DpiaScreeningResult:
    """Run one structured extraction, verify citations, and apply fixed rules."""

    cited = await client.structured_completion(
        dpia_screening_messages(snapshot.evidence_text),
        response_model=CitedDpiaScreeningInput,
        model=model,
        max_retries=2,
        temperature=0,
    )

    verified = verify_dpia_citations(cited, snapshot)
    return evaluate_dpia_screening(verified)
