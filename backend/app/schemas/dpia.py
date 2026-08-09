"""DPIA-owned persistence and API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
