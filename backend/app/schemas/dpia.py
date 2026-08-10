"""DPIA-owned persistence and API contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.screening import DpiaConclusion, DpiaScreeningResult


class DpiaEvidenceSnapshotEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    token: str = Field(pattern=r"^C[1-9][0-9]*$")
    chunk_id: UUID
    document_id: UUID
    document_name: str = Field(min_length=1)
    page: int | None
    section_title: str | None
    text: str = Field(min_length=1)


class DpiaEvidenceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    retrieval_version: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    embedding_dimensions: int = Field(gt=0)
    queries: tuple[str, ...] = Field(min_length=1)
    per_query_limit: int = Field(gt=0)
    evidence_limit: int = Field(gt=0)
    retrieved_at: datetime
    evidence_text: str = Field(min_length=1)
    entries: tuple[DpiaEvidenceSnapshotEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_snapshot_consistency(self) -> Self:
        if self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")

        if len(set(self.queries)) != len(self.queries):
            raise ValueError("snapshot queries must be unique")

        if len(self.entries) > self.evidence_limit:
            raise ValueError("snapshot contains more entries than its evidence limit")

        expected_tokens = [f"C{index}" for index in range(1, len(self.entries) + 1)]
        actual_tokens = [entry.token for entry in self.entries]
        if actual_tokens != expected_tokens:
            raise ValueError("snapshot entries must use contiguous citation tokens in order")

        token_positions = [self.evidence_text.find(f"[{token}]") for token in expected_tokens]
        if any(position < 0 for position in token_positions):
            raise ValueError("evidence text must contain every snapshot citation token")
        if token_positions != sorted(token_positions):
            raise ValueError("evidence text citation order must match snapshot entries")

        return self


class DpiaRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    READY_FOR_REVIEW = "ready_for_review"
    FAILED = "failed"


class DpiaScreeningRunRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
    )

    id: UUID
    project_id: UUID
    requested_by: UUID | None
    version: int = Field(gt=0)
    status: DpiaRunStatus
    evidence_snapshot: DpiaEvidenceSnapshot | None
    result: DpiaScreeningResult | None
    conclusion: DpiaConclusion | None
    model: str | None
    prompt_version: str | None
    rules_version: str = Field(min_length=1)
    error: str | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_run_lifecycle(self) -> Self:
        if not self.rules_version.strip():
            raise ValueError("rules_version must not be blank")

        if (
            self.evidence_snapshot is not None
            and self.evidence_snapshot.project_id != self.project_id
        ):
            raise ValueError("evidence snapshot must belong to the screening project")

        if self.status is DpiaRunStatus.PENDING:
            if any(
                value is not None
                for value in (
                    self.evidence_snapshot,
                    self.result,
                    self.conclusion,
                    self.model,
                    self.prompt_version,
                    self.error,
                )
            ):
                raise ValueError("pending screening must not contain generated artifacts")

        elif self.status is DpiaRunStatus.RUNNING:
            if any(
                value is not None
                for value in (
                    self.evidence_snapshot,
                    self.result,
                    self.conclusion,
                    self.model,
                    self.prompt_version,
                )
            ):
                raise ValueError("running screening must not contain generated results")

            if self.error is not None:
                raise ValueError("running screening must not contain an error")

        elif self.status is DpiaRunStatus.READY_FOR_REVIEW:
            if self.evidence_snapshot is None or self.result is None:
                raise ValueError("ready screening requires snapshot and result")
            if self.conclusion is None:
                raise ValueError("ready screening requires a conclusion")
            if self.error is not None:
                raise ValueError("ready screening must not contain an error")
            if not self.model or not self.model.strip():
                raise ValueError("ready screening requires a model")
            if not self.prompt_version or not self.prompt_version.strip():
                raise ValueError("ready screening requires a prompt version")
            if self.conclusion is not self.result.conclusion:
                raise ValueError("stored conclusion must match the screening result")

        elif self.status is DpiaRunStatus.FAILED:
            if not self.error or not self.error.strip():
                raise ValueError("failed screening requires a nonblank error")
            if any(
                value is not None
                for value in (
                    self.result,
                    self.conclusion,
                    self.model,
                    self.prompt_version,
                )
            ):
                raise ValueError("failed screening must not contain a result")

        return self
