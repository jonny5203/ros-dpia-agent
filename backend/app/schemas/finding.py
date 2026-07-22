from __future__ import annotations
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict

Severity = Literal["low", "medium", "high", "critical"]
Category = Literal["personal", "special_category"]

class FindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    type: str
    category: Category
    severity: Severity
    count: int
    sample_offset: list[list[int]] | None
    checksum_valid: bool | None

class DocumentWithFindings(BaseModel):
    document_id: UUID
    filename: str
    processing_status: str
    max_severity: Severity | None
    finding: list[FindingRead]
    acked_at: str | None = None
