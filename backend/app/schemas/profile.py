"""Pydantic schemas for the project profile.

The profile is what `extract_profile` (Pass A) produces; the gap-finder (Pass B)
fills `missingInfo` and `openQuestions`. Every leaf field that asserts a fact
must carry `sourceReferences: list[ChunkRef]` — grounding is a schema-level
obligation, enforced further by the citation-verification gate.
"""
from __future__ import annotations

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


class NamedReferencedList(Referenced):
    """A list of named items (e.g. systems, processors, data subjects)."""
    items: list[str] = Field(default_factory=list)


class Gap(BaseModel):
    """A missing-information finding produced by Pass B (red-team gap-finder).

    `field` names the profile field that has no supporting evidence;
    `description` is human-readable Norwegian/English per project language.
    """
    field: str
    description: str
    severity: Literal["info", "warning", "critical"] = "warning"


class OpenQuestion(BaseModel):
    """A follow-up question for the supplier / privacy officer (Pass B)."""
    question: str
    rationale: str | None = None


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
    created_at: str
