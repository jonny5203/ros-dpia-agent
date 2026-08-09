"""Shared bounded retrieval for evidence-backed project analysis."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from qdrant_client import AsyncQdrantClient

from app.ai.citations.evidence import EvidenceBlock, render_evidence
from app.ai.embeddings.service import embed_chunks
from app.ai.providers.base import EmbeddingClient
from app.ai.store.qdrant import hybrid_query

DEFAULT_EVIDENCE_LIMIT = 24
DEFAULT_PER_QUERY_LIMIT = 8


class RetrievalError(RuntimeError):
    """Project evidence could not be retrieved with trustworthy provenance."""


class NoRetrievedEvidenceError(RetrievalError):
    """The project has no usable indexed evidence."""


class DocumentNameLookup(Protocol):
    async def filenames_by_ids(
        self,
        project_id: UUID,
        document_ids: set[UUID],
    ) -> dict[UUID, str]: ...


def _normalise_result(raw: dict[str, Any]) -> dict[str, Any] | None:
    chunk_id = raw.get("chunk_id")
    document_id = raw.get("document_id")

    if chunk_id is None or document_id is None:
        raise RetrievalError("retrieved evidence is missing chunk or document provenance")

    try:
        parsed_chunk_id = UUID(str(chunk_id))
        parsed_document_id = UUID(str(document_id))
    except (TypeError, ValueError) as exc:
        raise RetrievalError("retrieved evidence contains malformed provenance") from exc

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


async def retrieve_project_evidence(
    *,
    project_id: UUID,
    queries: Sequence[str],
    qdrant: AsyncQdrantClient,
    client: EmbeddingClient,
    documents: DocumentNameLookup,
    per_query_limit: int = DEFAULT_PER_QUERY_LIMIT,
    evidence_limit: int = DEFAULT_EVIDENCE_LIMIT,
) -> EvidenceBlock:
    """Retrieve one exact project-owned evidence block for an assessment."""

    query_list = [query.strip() for query in queries]
    if not query_list:
        raise ValueError("at least one retrieval query is required")
    if any(not query for query in query_list):
        raise ValueError("retrieval queries must not be blank")
    if per_query_limit <= 0:
        raise ValueError("per-query limit must be positive")
    if evidence_limit <= 0:
        raise ValueError("evidence limit must be positive")

    vectors = await embed_chunks(query_list, client)
    if len(vectors) != len(query_list):
        raise RetrievalError("embedding provider returned an unexpected vector count")

    ranked_groups = await asyncio.gather(
        *(
            hybrid_query(
                qdrant,
                project_id=project_id,
                query_text=query,
                query_vector=vector,
                limit=per_query_limit,
            )
            for query, vector in zip(query_list, vectors, strict=True)
        )
    )

    chunks = merge_ranked_results(ranked_groups, limit=evidence_limit)
    if not chunks:
        raise NoRetrievedEvidenceError("project has no indexed evidence available for analysis")

    document_ids = {chunk["document_id"] for chunk in chunks}
    filenames = await documents.filenames_by_ids(project_id, document_ids)
    missing_documents = document_ids - set(filenames)

    if missing_documents:
        raise RetrievalError("retrieved evidence does not belong to an available project document")

    enriched_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        filename = filenames[chunk["document_id"]].strip()
        if not filename:
            raise RetrievalError("retrieved evidence has empty document provenance")

        enriched_chunks.append(
            {
                **chunk,
                "document_name": filename,
            }
        )

    evidence = render_evidence(enriched_chunks)
    if not evidence.token_map:
        raise NoRetrievedEvidenceError("project has no indexed evidence available for analysis")

    return evidence
