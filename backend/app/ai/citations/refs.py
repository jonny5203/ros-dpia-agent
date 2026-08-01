"""LLM-facing citation ref types (plan §9, §10.2).

The model emits `Cn` string tokens (it never sees UUIDs). The gate resolves
these tokens to real chunk UUIDs and emits persisted `ChunkRef` objects with
typed UUIDs. Two worlds, one boundary (the gate).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.profile import OverallConfidence


class CitedRef(BaseModel):
    """A citation as the model emits it — an opaque `[Cn]` token."""

    citation: str


class Cited(BaseModel):
    """LLM-facing scalar value that asserts a fact.

    Mirrors `app.schemas.profile.Referenced` but with string citations instead
    of typed UUIDs, so the LLM can only emit `[Cn]` tokens it was shown.
    """

    sourceReferences: list[CitedRef] = Field(default_factory=list)
    value: str | None = None


class CitedItem(BaseModel):
    """One LLM-emitted list item with its own opaque citation tokens."""

    value: str
    sourceReferences: list[CitedRef] = Field(default_factory=list)


class CitedNamed(BaseModel):
    """LLM-facing list whose items are verified independently."""

    items: list[CitedItem] = Field(default_factory=list)


class CitedProjectProfile(BaseModel):
    """Pass-A output before opaque citations are resolved to persisted UUID refs."""

    model_config = ConfigDict(extra="forbid")

    purpose: Cited
    dataSubjects: CitedNamed
    personalDataCategories: CitedNamed
    specialCategories: CitedNamed
    systems: CitedNamed
    processors: CitedNamed
    retention: Cited
    accessControl: Cited
    internationalTransfer: Cited
    overallConfidence: OverallConfidence = "medium"
