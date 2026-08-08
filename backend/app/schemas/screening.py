"""Strict contracts for deterministic DPIA screening."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.chunk import ChunkRef


class DpiaConclusion(StrEnum):
    REQUIRED = "DPIA_REQUIRED"
    LIKELY = "DPIA_LIKELY"
    NOT_INDICATED = "DPIA_NOT_INDICATED"


class CriterionStatus(StrEnum):
    TRIGGERED = "triggered"
    NOT_TRIGGERED = "not_triggered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class DpiaCriterionId(StrEnum):
    EVALUATION = "evaluation_or_scoring"
    AUTOMATED_DECISION = "automated_decision_with_significant_effect"
    SYSTEMATIC_MONITORING = "systematic_monitoring"
    SENSITIVE_DATA = "sensitive_or_highly_personal_data"
    LARGE_SCALE = "large_scale_processing"
    DATASET_MATCHING = "dataset_matching"
    VULNERABLE_SUBJECTS = "vulnerable_data_subjects"
    NEW_TECHNOLOGY = "innovative_or_new_technology"
    RIGHT_OR_SERVICE = "prevents_right_service_or_contract"


class Art35TriggerId(StrEnum):
    AUTOMATED_EVALUATION = "systematic_extensive_automated_evaluation"
    LARGE_SCALE_SENSITIVE_DATA = "large_scale_sensitive_or_criminal_data"
    PUBLIC_AREA_MONITORING = "large_scale_public_area_monitoring"


class _EvidenceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CriterionStatus
    rationale: str = Field(min_length=1)
    sourceReferences: list[ChunkRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_citations_for_decisive_status(self) -> Self:
        if self.status is not CriterionStatus.INSUFFICIENT_EVIDENCE and not self.sourceReferences:
            raise ValueError("decisive assessments require at least one verified citation")
        return self


class DpiaCriterionAssessment(_EvidenceAssessment):
    id: DpiaCriterionId


class Art35TriggerAssessment(_EvidenceAssessment):
    id: Art35TriggerId


class DpiaScreeningInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[DpiaCriterionAssessment]
    art35_3: list[Art35TriggerAssessment]

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


class DpiaCriterionResult(DpiaCriterionAssessment):
    label_nb: str


class Art35TriggerResult(Art35TriggerAssessment):
    label_nb: str


class DpiaScreeningResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[DpiaCriterionResult]
    art35_3: list[Art35TriggerResult]
    criteria_count: int = Field(ge=0, le=9)
    art35_3_triggered: bool
    conclusion: DpiaConclusion
    evidence_incomplete: bool
    requires_human_review: bool
    rationale_nb: str
