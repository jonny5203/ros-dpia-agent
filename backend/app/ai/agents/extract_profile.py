"""Two-pass, citation-gated project-profile extraction."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from qdrant_client import AsyncQdrantClient

from app.ai.citations.evidence import EvidenceBlock, render_evidence
from app.ai.citations.gate import verify_profile
from app.ai.citations.refs import CitedProjectProfile
from app.ai.embeddings.service import embed_chunks
from app.ai.prompts.profile import (
    PROFILE_PROMPT_VERSION,
    OutputLanguage,
    gap_messages,
    profile_messages,
)
from app.ai.providers.base import ProfileAIClient
from app.ai.store.qdrant import hybrid_query
from app.db.models import ProjectProfiles
from app.schemas.profile import GapReport

DEFAULT_EVIDENCE_LIMIT = 24
_PER_QUERY_LIMIT = 8

RETRIEVAL_QUERIES = (
    (
        "prosjektformål behandlingsaktiviteter registrerte personopplysninger "
        "project purpose processing activities data subjects"
    ),
    (
        "personopplysningskategorier særlige kategorier behandlingsgrunnlag "
        "personal data categories special categories"
    ),
    (
        "systemarkitektur leverandører databehandlere underleverandører "
        "data location international transfer systems processors"
    ),
    (
        "lagringstid sletting tilgangsstyring autentisering logging sikkerhet "
        "retention deletion access control authentication security"
    ),
)


class ProfileExtractionError(RuntimeError):
    """Profile extraction could not safely produce a persisted result."""


class NoEvidenceError(ProfileExtractionError):
    """The project has no usable indexed evidence."""


class DocumentNameLookup(Protocol):
    async def filenames_by_ids(
        self,
        project_id: UUID,
        document_ids: set[UUID],
    ) -> dict[UUID, str]: ...


class ProfileWriter(Protocol):
    async def create(
        self,
        *,
        project_id: UUID,
        profile: dict,
        overall_confidence: str,
        model: str,
        prompt_version: str,
    ) -> ProjectProfiles: ...


def _normalise_result(raw: dict[str, Any]) -> dict[str, Any] | None:
    chunk_id = raw.get("chunk_id")
    document_id = raw.get("document_id")
    if chunk_id is None or document_id is None:
        raise ProfileExtractionError("retrieved evidence is missing chunk or document provenance")

    try:
        parsed_chunk_id = UUID(str(chunk_id))
        parsed_document_id = UUID(str(document_id))
    except ValueError as exc:
        raise ProfileExtractionError("retrieved evidence contains malformed provenance") from exc

    text = str(raw.get("text") or "").strip()
    if not text:
        return None

    return {
        **raw,
        "chunk_id": parsed_chunk_id,
        "document_id": parsed_document_id,
        "text": text,
    }


def merge_ranked_results(
    ranked_groups: Sequence[Sequence[dict[str, Any]]],
    *,
    limit: int = DEFAULT_EVIDENCE_LIMIT,
) -> list[dict[str, Any]]:
    """Interleave query ranks, deduplicate chunks, and enforce the evidence cap."""

    if limit <= 0:
        raise ValueError("evidence limit must be positive")

    merged: list[dict[str, Any]] = []
    seen: set[UUID] = set()
    max_group_size = max((len(group) for group in ranked_groups), default=0)

    for rank in range(max_group_size):
        for group in ranked_groups:
            if rank >= len(group):
                continue

            result = _normalise_result(group[rank])
            if result is None:
                continue

            chunk_id = result["chunk_id"]
            if chunk_id in seen:
                continue

            seen.add(chunk_id)
            merged.append(result)
            if len(merged) == limit:
                return merged

    return merged


async def _retrieve_evidence(
    *,
    project_id: UUID,
    qdrant: AsyncQdrantClient,
    client: ProfileAIClient,
    documents: DocumentNameLookup,
) -> EvidenceBlock:
    queries = list(RETRIEVAL_QUERIES)
    vectors = await embed_chunks(queries, client)
    if len(vectors) != len(queries):
        raise ProfileExtractionError("embedding provider returned an unexpected vector count")

    ranked_groups = await asyncio.gather(
        *(
            hybrid_query(
                qdrant,
                project_id=project_id,
                query_text=query,
                query_vector=vector,
                limit=_PER_QUERY_LIMIT,
            )
            for query, vector in zip(queries, vectors, strict=True)
        )
    )
    chunks = merge_ranked_results(ranked_groups)
    if not chunks:
        raise NoEvidenceError("project has no indexed evidence available for analysis")

    document_ids = {chunk["document_id"] for chunk in chunks}
    filenames = await documents.filenames_by_ids(project_id, document_ids)
    missing_documents = document_ids - filenames.keys()
    if missing_documents:
        raise ProfileExtractionError(
            "retrieved evidence does not belong to an available project document"
        )

    for chunk in chunks:
        chunk["document_name"] = filenames[chunk["document_id"]]

    evidence = render_evidence(chunks)
    if not evidence.token_map:
        raise NoEvidenceError("project has no indexed evidence available for analysis")
    return evidence


async def extract_profile(
    *,
    project_id: UUID,
    model: str,
    qdrant: AsyncQdrantClient,
    client: ProfileAIClient,
    documents: DocumentNameLookup,
    profiles: ProfileWriter,
    output_language: OutputLanguage = "nb",
) -> ProjectProfiles:
    """Run both passes and stage one safe profile row.

    The caller owns the database transaction and must commit on success or
    roll back on failure.
    """

    evidence = await _retrieve_evidence(
        project_id=project_id,
        qdrant=qdrant,
        client=client,
        documents=documents,
    )

    cited_profile = await client.structured_completion(
        profile_messages(evidence.text, output_language),
        response_model=CitedProjectProfile,
        model=model,
        max_retries=2,
        temperature=0,
    )
    gate_result = verify_profile(cited_profile, evidence.token_map)

    gap_report = await client.structured_completion(
        gap_messages(gate_result.profile, evidence.text, output_language),
        response_model=GapReport,
        model=model,
        max_retries=2,
        temperature=0,
    )

    safe_profile = gate_result.profile.model_copy(
        update={
            "missingInfo": gap_report.missingInfo,
            "openQuestions": gap_report.openQuestions,
        }
    )

    return await profiles.create(
        project_id=project_id,
        profile=safe_profile.model_dump(mode="json"),
        overall_confidence=safe_profile.overallConfidence,
        model=model,
        prompt_version=PROFILE_PROMPT_VERSION,
    )
