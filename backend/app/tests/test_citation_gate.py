"""Citation-gate contract tests (plan §10.3)."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.ai.citations.evidence import render_evidence
from app.ai.citations.gate import resolve_tokens, verify_profile
from app.ai.citations.refs import Cited, CitedItem, CitedNamed, CitedProjectProfile, CitedRef

CID_A = UUID("00000000-0000-0000-0000-000000000001")
CID_B = UUID("00000000-0000-0000-0000-000000000002")
DOC_ID = UUID("11111111-1111-1111-1111-111111111111")

_CHUNKS = [
    {
        "chunk_id": str(CID_A),
        "document_id": str(DOC_ID),
        "page": 1,
        "document_name": "Systembeskrivelse.pdf",
        "section_title": "System",
        "text": "HSO assistant uses Azure OpenAI.",
    },
    {
        "chunk_id": str(CID_B),
        "document_id": str(DOC_ID),
        "page": 2,
        "document_name": "Systembeskrivelse.pdf",
        "section_title": "Processor",
        "text": "Microsoft is the processor.",
    },
]


def _profile(
    *,
    purpose: Cited | None = None,
    systems: CitedNamed | None = None,
    retention: Cited | None = None,
) -> CitedProjectProfile:
    return CitedProjectProfile(
        purpose=purpose or Cited(),
        dataSubjects=CitedNamed(),
        personalDataCategories=CitedNamed(),
        specialCategories=CitedNamed(),
        systems=systems or CitedNamed(),
        processors=CitedNamed(),
        retention=retention or Cited(),
        accessControl=Cited(),
        internationalTransfer=Cited(),
    )


def test_evidence_renders_opaque_tokens_and_builds_token_map():
    block = render_evidence(_CHUNKS)
    assert "[C1]" in block.text and "[C2]" in block.text
    assert "00000000" not in block.text
    assert set(block.token_map) == {"C1", "C2"}
    assert block.token_map["C1"].chunk_id == CID_A


def test_resolve_tokens_splits_verified_from_unverified():
    block = render_evidence(_CHUNKS)
    verified, unverified = resolve_tokens(["C1", "C999", "C2"], block.token_map)
    assert [entry.chunk_id for entry in verified] == [CID_A, CID_B]
    assert unverified == ["C999"]


def test_resolve_tokens_empty_for_unknown_only():
    block = render_evidence(_CHUNKS)
    verified, unverified = resolve_tokens(["C999"], block.token_map)
    assert verified == []
    assert unverified == ["C999"]


def test_gate_rejects_evidence_without_document_provenance():
    block = render_evidence([{"chunk_id": str(CID_A), "page": 1, "text": "orphaned evidence"}])
    profile = _profile(purpose=Cited(value="orphaned", sourceReferences=[CitedRef(citation="C1")]))

    with pytest.raises(ValueError, match="missing required document provenance"):
        verify_profile(profile, block.token_map)


def test_gate_accepts_grounded_claim():
    block = render_evidence(_CHUNKS)
    profile = _profile(
        purpose=Cited(value="HSO assistant", sourceReferences=[CitedRef(citation="C1")])
    )
    result = verify_profile(profile, block.token_map)
    assert result is not None

    purpose = result.profile.purpose

    assert purpose.value == "HSO assistant"
    assert purpose.verificationStatus == "grounded"
    assert not purpose.evidenceMissing
    assert [ref.chunkId for ref in purpose.sourceReferences] == [CID_A]
    assert [ref.chunkId for ref in result.verified] == [CID_A]
    assert not result.unverified
    assert not result.needs_review


def test_gate_quarantines_fabricated_c999():
    block = render_evidence(_CHUNKS)
    profile = _profile(purpose=Cited(value="made up", sourceReferences=[CitedRef(citation="C999")]))
    result = verify_profile(profile, block.token_map)
    assert result is not None

    purpose = result.profile.purpose
    quarantined = result.needs_review[0]

    assert not result.verified
    assert result.unverified == ["C999"]
    assert purpose.value is None
    assert purpose.sourceReferences == []
    assert purpose.verificationStatus == "unverified"
    assert purpose.evidenceMissing is True
    assert len(result.needs_review) == 1
    assert quarantined.fieldPath == "purpose"
    assert quarantined.value == "made up"
    assert quarantined.sourceReferences == []
    assert quarantined.unverifiedCitations == ["C999"]
    assert quarantined.verificationStatus == "unverified"
    assert quarantined.evidenceMissing is True


def test_gate_retains_mixed_scalar_as_partial():
    block = render_evidence(_CHUNKS)
    profile = _profile(
        purpose=Cited(
            value="mixed",
            sourceReferences=[CitedRef(citation="C1"), CitedRef(citation="C999")],
        )
    )
    result = verify_profile(profile, block.token_map)
    assert result is not None

    purpose = result.profile.purpose

    assert purpose.value == "mixed"
    assert purpose.verificationStatus == "partial"
    assert purpose.evidenceMissing is True
    assert [ref.chunkId for ref in purpose.sourceReferences] == [CID_A]
    assert [ref.chunkId for ref in result.verified] == [CID_A]
    assert result.unverified == ["C999"]
    assert not result.needs_review


def test_gate_quarantines_value_without_references():
    block = render_evidence(_CHUNKS)
    profile = _profile(retention=Cited(value="5 years"))
    result = verify_profile(profile, block.token_map)
    assert result is not None

    retention = result.profile.retention
    quarantined = result.needs_review[0]

    assert retention.value is None
    assert retention.sourceReferences == []
    assert retention.verificationStatus == "unverified"
    assert retention.evidenceMissing is True
    assert not result.verified
    assert not result.unverified
    assert len(result.needs_review) == 1
    assert quarantined.fieldPath == "retention"
    assert quarantined.value == "5 years"
    assert quarantined.sourceReferences == []
    assert quarantined.unverifiedCitations == []
    assert quarantined.verificationStatus == "unverified"
    assert quarantined.evidenceMissing is True


def test_gate_quarantines_only_the_unsupported_list_item():
    block = render_evidence(_CHUNKS)
    profile = _profile(
        systems=CitedNamed(
            items=[
                CitedItem(value="Azure OpenAI", sourceReferences=[CitedRef(citation="C1")]),
                CitedItem(
                    value="Imaginary System",
                    sourceReferences=[CitedRef(citation="C999")],
                ),
            ]
        )
    )
    result = verify_profile(profile, block.token_map)
    assert result is not None

    systems = result.profile.systems.items
    quarantined = result.needs_review[0]

    assert len(systems) == 1
    assert systems[0].value == "Azure OpenAI"
    assert systems[0].verificationStatus == "grounded"
    assert not systems[0].evidenceMissing
    assert [ref.chunkId for ref in systems[0].sourceReferences] == [CID_A]
    assert [ref.chunkId for ref in result.verified] == [CID_A]
    assert result.unverified == ["C999"]
    assert len(result.needs_review) == 1
    assert quarantined.fieldPath == "systems.items[1]"
    assert quarantined.value == "Imaginary System"
    assert quarantined.sourceReferences == []
    assert quarantined.unverifiedCitations == ["C999"]
    assert quarantined.verificationStatus == "unverified"
    assert quarantined.evidenceMissing is True
