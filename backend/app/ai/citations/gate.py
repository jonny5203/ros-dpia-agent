"""Deterministic citation-verification gate (plan §10.3).

The gate resolves opaque model citations against the exact EVIDENCE set, builds
a safe persisted ``ProjectProfile``, and quarantines unsupported assertions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.citations.evidence import EvidenceEntry
from app.ai.citations.refs import Cited, CitedItem, CitedProjectProfile
from app.schemas.chunk import ChunkRef
from app.schemas.profile import (
    NamedReferencedList,
    NeedsReviewClaim,
    ProjectProfile,
    ReferencedItem,
    ReferencedValue,
    VerificationStatus,
)


@dataclass
class GateResult:
    """Safe profile plus aggregate verification metadata for audit/tests."""

    profile: ProjectProfile
    verified: list[ChunkRef] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> list[NeedsReviewClaim]:
        return self.profile.needsReview

    @property
    def is_clean(self) -> bool:
        return not self.unverified and not self.needs_review


# Explicit field inventories prevent a newly added profile field from silently
# bypassing verification. Scalars and named-list items have different shapes.
_SCALAR_FIELDS = ("purpose", "retention", "accessControl", "internationalTransfer")
_LIST_FIELDS = (
    "dataSubjects",
    "personalDataCategories",
    "specialCategories",
    "systems",
    "processors",
)


def resolve_tokens(
    tokens: list[str], token_map: dict[str, EvidenceEntry]
) -> tuple[list[EvidenceEntry], list[str]]:
    """Return verified entries and unknown tokens without changing input order."""

    verified: list[EvidenceEntry] = []
    unverified: list[str] = []
    for token in tokens:
        entry = token_map.get(token)
        if entry is None:
            unverified.append(token)
        else:
            verified.append(entry)
    return verified, unverified


def _to_chunk_ref(entry: EvidenceEntry) -> ChunkRef:
    if entry.document_id is None:
        raise ValueError(f"evidence {entry.token} is missing required document provenance")
    return ChunkRef(
        chunkId=entry.chunk_id,
        documentId=entry.document_id,
        documentName=entry.document_name,
        page=entry.page,
        sectionTitle=entry.section_title,
    )


def _classify(
    *,
    has_verified: bool,
    has_unverified: bool,
    had_value: bool,
) -> tuple[VerificationStatus, bool]:
    """Decide ``(verificationStatus, evidenceMissing)`` for one assertion."""

    if has_verified and not has_unverified and had_value:
        return "grounded", False

    if has_verified and has_unverified and had_value:
        return "partial", True

    return "unverified", True


def _record_refs(
    result_verified: list[ChunkRef],
    result_unverified: list[str],
    verified_entries: list[EvidenceEntry],
    unverified_tokens: list[str],
) -> list[ChunkRef]:
    """Convert/deduplicate per-claim data into aggregate gate metadata."""

    refs = [_to_chunk_ref(entry) for entry in verified_entries]
    for ref in refs:
        if ref not in result_verified:
            result_verified.append(ref)
    for token in unverified_tokens:
        if token not in result_unverified:
            result_unverified.append(token)
    return refs


def _verify_scalar(
    *,
    field_path: str,
    leaf: Cited,
    token_map: dict[str, EvidenceEntry],
    verified: list[ChunkRef],
    unverified: list[str],
    needs_review: list[NeedsReviewClaim],
) -> ReferencedValue:
    tokens = [ref.citation for ref in leaf.sourceReferences]
    verified_entries, unverified_tokens = resolve_tokens(tokens, token_map)
    refs = _record_refs(verified, unverified, verified_entries, unverified_tokens)
    had_value = bool(leaf.value)
    status, evidence_missing = _classify(
        has_verified=bool(refs),
        has_unverified=bool(unverified_tokens),
        had_value=had_value,
    )

    if had_value and not refs:
        needs_review.append(
            NeedsReviewClaim(
                fieldPath=field_path,
                value=leaf.value or "",
                unverifiedCitations=unverified_tokens,
                evidenceMissing=evidence_missing,
                verificationStatus=status,
            )
        )
        safe_value = None
    else:
        safe_value = leaf.value

    return ReferencedValue(
        value=safe_value,
        sourceReferences=refs,
        evidenceMissing=evidence_missing,
        verificationStatus=status,
    )


def _verify_item(
    *,
    field_path: str,
    item: CitedItem,
    token_map: dict[str, EvidenceEntry],
    verified: list[ChunkRef],
    unverified: list[str],
    needs_review: list[NeedsReviewClaim],
) -> ReferencedItem | None:
    tokens = [ref.citation for ref in item.sourceReferences]
    verified_entries, unverified_tokens = resolve_tokens(tokens, token_map)
    refs = _record_refs(verified, unverified, verified_entries, unverified_tokens)
    status, evidence_missing = _classify(
        has_verified=bool(refs),
        has_unverified=bool(unverified_tokens),
        had_value=bool(item.value),
    )

    if not refs:
        needs_review.append(
            NeedsReviewClaim(
                fieldPath=field_path,
                value=item.value,
                unverifiedCitations=unverified_tokens,
                evidenceMissing=evidence_missing,
                verificationStatus=status,
            )
        )
        return None

    return ReferencedItem(
        value=item.value,
        sourceReferences=refs,
        evidenceMissing=evidence_missing,
        verificationStatus=status,
    )


def verify_profile(
    cited_profile: CitedProjectProfile,
    token_map: dict[str, EvidenceEntry],
) -> GateResult:
    """Resolve an LLM profile into the only profile safe to persist/display."""

    verified: list[ChunkRef] = []
    unverified: list[str] = []
    needs_review: list[NeedsReviewClaim] = []
    safe_scalars: dict[str, ReferencedValue] = {}
    safe_lists: dict[str, NamedReferencedList] = {}

    for field_name in _SCALAR_FIELDS:
        safe_scalars[field_name] = _verify_scalar(
            field_path=field_name,
            leaf=getattr(cited_profile, field_name),
            token_map=token_map,
            verified=verified,
            unverified=unverified,
            needs_review=needs_review,
        )

    for field_name in _LIST_FIELDS:
        cited_list = getattr(cited_profile, field_name)
        safe_items: list[ReferencedItem] = []
        for index, item in enumerate(cited_list.items):
            safe_item = _verify_item(
                field_path=f"{field_name}.items[{index}]",
                item=item,
                token_map=token_map,
                verified=verified,
                unverified=unverified,
                needs_review=needs_review,
            )
            if safe_item is not None:
                safe_items.append(safe_item)
        safe_lists[field_name] = NamedReferencedList(items=safe_items)

    profile = ProjectProfile(
        purpose=safe_scalars["purpose"],
        dataSubjects=safe_lists["dataSubjects"],
        personalDataCategories=safe_lists["personalDataCategories"],
        specialCategories=safe_lists["specialCategories"],
        systems=safe_lists["systems"],
        processors=safe_lists["processors"],
        retention=safe_scalars["retention"],
        accessControl=safe_scalars["accessControl"],
        internationalTransfer=safe_scalars["internationalTransfer"],
        missingInfo=[],
        openQuestions=[],
        needsReview=needs_review,
        overallConfidence=cited_profile.overallConfidence,
    )
    return GateResult(profile=profile, verified=verified, unverified=unverified)
