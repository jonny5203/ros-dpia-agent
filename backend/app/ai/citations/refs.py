"""LLM-facing citation ref types.

The model emits `Cn` string tokens (it never sees UUIDs). The gate resolves
these tokens to real chunk UUIDs and emits persisted `ChunkRef` objects with
typed UUIDs. Two worlds, one boundary (the gate).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.profile import OverallConfidence


class CitedRef(BaseModel):
    """A citation as the model emits it — an opaque `[Cn]` token."""

    model_config = ConfigDict(extra="forbid")

    citation: str


class Cited(BaseModel):
    """An LLM-facing scalar value that asserts a fact."""

    model_config = ConfigDict(extra="forbid")

    sourceReferences: list[CitedRef]
    value: str | None


class CitedItem(BaseModel):
    """One LLM-emitted list item with independently checked citations."""

    model_config = ConfigDict(extra="forbid")

    value: str
    sourceReferences: list[CitedRef]


class CitedNamed(BaseModel):
    """An LLM-facing list whose items are verified independently."""

    model_config = ConfigDict(extra="forbid")

    items: list[CitedItem]


class CitedProjectProfile(BaseModel):
    """Pass-A output before opaque citations become persisted UUID refs."""

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
    overallConfidence: OverallConfidence
