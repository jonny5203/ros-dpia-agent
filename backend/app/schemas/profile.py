"""Pydantic schemas for the project profile.

The profile is what `extract_profile` (Pass A) produces; the gap-finder (Pass B)
fills `missingInfo` and `openQuestions`. Every leaf field that asserts a fact
must carry `sourceReferences: list[ChunkRef]` — grounding is a schema-level
obligation, enforced further by the citation-verification gate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.chunk import ChunkRef

# Cautious framing is enforced structurally: there is NO "compliant" /
# "non_compliant" value the model can emit. The model literally cannot
# produce a forbidden compliance verdict.
VerificationStatus = Literal["grounded", "partial", "unverified"]
OverallConfidence = Literal["high", "medium", "low"]


class Referenced(BaseModel):
    """Base for any leaf field that asserts a fact and therefore must cite chunks.

    The citation-verification gate walks every `sourceReferences` list and
    checks membership against the EVIDENCE set the model actually saw.
    """

    sourceReferences: list[ChunkRef] = Field(default_factory=list)
    evidenceMissing: bool = False
    verificationStatus: VerificationStatus | None = None


class ReferencedValue(Referenced):
    """A scalar fact with citations (e.g. purpose, retention)."""

    value: str | None = None


class ReferencedItem(Referenced):
    """One independently grounded item in a named profile list."""

    value: str


class NamedReferencedList(BaseModel):
    """A list whose individual items carry their own citation contract."""

    items: list[ReferencedItem] = Field(default_factory=list)


class NeedsReviewClaim(BaseModel):
    """An asserted value removed from the trusted profile by the citation gate."""

    fieldPath: str
    value: str
    sourceReferences: list[ChunkRef] = Field(default_factory=list)
    unverifiedCitations: list[str] = Field(default_factory=list)
    evidenceMissing: bool = True
    verificationStatus: VerificationStatus = "unverified"


class ProjectProfile(BaseModel):
    """The structured project profile. The LLM populates this; downstream
    consumers (the rules engine, the ROS generator) read from it.
    """

    model_config = ConfigDict(extra="forbid")

    purpose: ReferencedValue
    dataSubjects: NamedReferencedList
    personalDataCategories: NamedReferencedList
    specialCategories: NamedReferencedList
    systems: NamedReferencedList
    processors: NamedReferencedList
    retention: ReferencedValue
    accessControl: ReferencedValue
    internationalTransfer: ReferencedValue

    # Filled by Pass B (gap-finder); left empty by Pass A.
    missingInfo: list[Gap] = Field(default_factory=list)
    openQuestions: list[OpenQuestion] = Field(default_factory=list)

    # Filled by the deterministic citation gate before persistence/display.
    needsReview: list[NeedsReviewClaim] = Field(default_factory=list)

    overallConfidence: OverallConfidence = "medium"


class ProjectProfileRead(BaseModel):
    """API read shape for `GET /projects/{id}/profile` — the persisted row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    profile: ProjectProfile
    overall_confidence: OverallConfidence
    model: str
    prompt_version: str
    created_at: datetime


class Gap(BaseModel):
    """A missing-information finding produced by Pass B."""

    model_config = ConfigDict(extra="forbid")

    field: str
    description: str
    severity: Literal["info", "warning", "critical"]


class OpenQuestion(BaseModel):
    """A follow-up question for the supplier or privacy officer."""

    model_config = ConfigDict(extra="forbid")

    question: str
    rationale: str | None


class GapReport(BaseModel):
    """Strict Pass-B response before it is merged into the safe profile."""

    model_config = ConfigDict(extra="forbid")

    missingInfo: list[Gap]
    openQuestions: list[OpenQuestion]
