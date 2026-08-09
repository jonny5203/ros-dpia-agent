"""Contract tests for DPIA-specific retrieval and evidence snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from qdrant_client import AsyncQdrantClient

from app.ai.dpia.retrieval import (
    DPIA_EVIDENCE_LIMIT,
    DPIA_PER_QUERY_LIMIT,
    DPIA_RETRIEVAL_QUERIES,
    DPIA_RETRIEVAL_VERSION,
    retrieve_dpia_evidence,
)
from app.ai.retrieval import (
    NoRetrievedEvidenceError,
    RetrievalError,
    retrieve_project_evidence,
)
from app.core.config import get_settings
from app.schemas.dpia import DpiaEvidenceSnapshot

PROJECT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DOCUMENT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
RETRIEVED_AT = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        self.calls.append(list(texts))
        dimensions = get_settings().embed_dim
        return [[0.0] * dimensions for _ in texts]


class FakeDocumentNames:
    def __init__(self, names: dict[UUID, str]) -> None:
        self.names = names
        self.calls: list[tuple[UUID, set[UUID]]] = []

    async def filenames_by_ids(
        self,
        project_id: UUID,
        document_ids: set[UUID],
    ) -> dict[UUID, str]:
        self.calls.append((project_id, document_ids))
        return {
            document_id: self.names[document_id]
            for document_id in document_ids
            if document_id in self.names
        }


def _qdrant() -> AsyncQdrantClient:
    return cast(AsyncQdrantClient, object())


def _chunk(number: int, text: str) -> dict[str, Any]:
    return {
        "chunk_id": str(UUID(int=number)),
        "document_id": str(DOCUMENT_ID),
        "page": number,
        "section_title": f"Section {number}",
        "text": text,
        "score": 1.0 / number,
    }


@pytest.mark.asyncio
async def test_retrieve_dpia_evidence_builds_exact_immutable_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query_calls: list[str] = []

    async def fake_hybrid_query(
        qdrant: AsyncQdrantClient,
        *,
        project_id: UUID,
        query_text: str,
        query_vector: list[float],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        query_calls.append(query_text)
        if query_text == DPIA_RETRIEVAL_QUERIES[0]:
            return [
                _chunk(1, "Systemet profilerer søkere."),
                _chunk(2, "Behandlingen omfatter helseopplysninger."),
            ][:limit]
        return [_chunk(2, "Duplikat som ikke skal endre første forekomst.")][:limit]

    monkeypatch.setattr(
        "app.ai.retrieval.hybrid_query",
        fake_hybrid_query,
    )

    client = FakeEmbeddingClient()
    documents = FakeDocumentNames({DOCUMENT_ID: "Systembeskrivelse.pdf"})

    result = await retrieve_dpia_evidence(
        project_id=PROJECT_ID,
        qdrant=_qdrant(),
        client=client,
        documents=documents,
        retrieved_at=RETRIEVED_AT,
    )

    settings = get_settings()
    snapshot = result.snapshot

    assert query_calls == list(DPIA_RETRIEVAL_QUERIES)
    assert client.calls == [list(DPIA_RETRIEVAL_QUERIES)]
    assert documents.calls == [(PROJECT_ID, {DOCUMENT_ID})]

    assert snapshot.project_id == PROJECT_ID
    assert snapshot.retrieval_version == DPIA_RETRIEVAL_VERSION
    assert snapshot.embedding_model == settings.embed_model
    assert snapshot.embedding_dimensions == settings.embed_dim
    assert snapshot.queries == DPIA_RETRIEVAL_QUERIES
    assert snapshot.per_query_limit == DPIA_PER_QUERY_LIMIT
    assert snapshot.evidence_limit == DPIA_EVIDENCE_LIMIT
    assert snapshot.retrieved_at == RETRIEVED_AT
    assert snapshot.evidence_text == result.block.text

    assert [entry.token for entry in snapshot.entries] == ["C1", "C2"]
    assert snapshot.entries[0].text == "Systemet profilerer søkere."
    assert snapshot.entries[1].text == ("Duplikat som ikke skal endre første forekomst.")
    assert all(entry.document_id == DOCUMENT_ID for entry in snapshot.entries)
    assert all(entry.document_name == "Systembeskrivelse.pdf" for entry in snapshot.entries)

    dumped = snapshot.model_dump(mode="json")
    assert dumped["entries"][0]["text"] == "Systemet profilerer søkere."
    assert DpiaEvidenceSnapshot.model_validate(dumped) == snapshot

    with pytest.raises(ValidationError, match="frozen"):
        snapshot.retrieval_version = "changed"


@pytest.mark.asyncio
async def test_retrieve_dpia_evidence_rejects_no_indexed_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_results(
        qdrant: AsyncQdrantClient,
        *,
        project_id: UUID,
        query_text: str,
        query_vector: list[float],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(
        "app.ai.retrieval.hybrid_query",
        no_results,
    )

    with pytest.raises(
        NoRetrievedEvidenceError,
        match="no indexed evidence",
    ):
        await retrieve_dpia_evidence(
            project_id=PROJECT_ID,
            qdrant=_qdrant(),
            client=FakeEmbeddingClient(),
            documents=FakeDocumentNames({}),
            retrieved_at=RETRIEVED_AT,
        )


@pytest.mark.asyncio
async def test_retrieve_dpia_evidence_rejects_document_outside_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def one_result(
        qdrant: AsyncQdrantClient,
        *,
        project_id: UUID,
        query_text: str,
        query_vector: list[float],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return [_chunk(1, "Evidence")]

    monkeypatch.setattr(
        "app.ai.retrieval.hybrid_query",
        one_result,
    )

    with pytest.raises(
        RetrievalError,
        match="available project document",
    ):
        await retrieve_dpia_evidence(
            project_id=PROJECT_ID,
            qdrant=_qdrant(),
            client=FakeEmbeddingClient(),
            documents=FakeDocumentNames({}),
            retrieved_at=RETRIEVED_AT,
        )


@pytest.mark.asyncio
async def test_retrieval_rejects_empty_query_inventory_before_embedding() -> None:
    client = FakeEmbeddingClient()

    with pytest.raises(
        ValueError,
        match="at least one retrieval query",
    ):
        await retrieve_project_evidence(
            project_id=PROJECT_ID,
            queries=(),
            qdrant=_qdrant(),
            client=client,
            documents=FakeDocumentNames({}),
        )

    assert client.calls == []
