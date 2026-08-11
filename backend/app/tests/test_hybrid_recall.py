"""Integration test: hybrid_query returns dense + BM25 results fused by RRF.

Marked `slow` (live Qdrant). Embeddings are dummy small-dim vectors to avoid
the OpenRouter dependency; the test exercises the query/fusion logic, not
embedding quality.
"""

from __future__ import annotations

import os
import uuid

import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

from app.ai.store.qdrant import hybrid_query, upsert_chunks

pytestmark = pytest.mark.slow


@pytest.fixture
async def qdrant_with_data():
    """Spin up a collection with two known chunks, yield (client, project_id)."""
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    client = AsyncQdrantClient(url=url)
    project_id = uuid.uuid4()
    coll = f"chunks_{project_id}"

    await client.create_collection(
        collection_name=coll,
        vectors_config={"dense": qm.VectorParams(size=4, distance=qm.Distance.COSINE)},
        sparse_vectors_config={
            "bm25": qm.SparseVectorParams(
                index=qm.SparseIndexParams(),
                modifier=qm.Modifier.IDF,
            )
        },
    )
    await client.create_payload_index(
        collection_name=coll, field_name="text",
        field_schema=qm.TextIndexParams(
            type=qm.TextIndexType.TEXT,
            tokenizer=qm.TokenizerType.WORD,
            lowercase=True,
        ),
    )

    points = [
        {"id": "c1", "dense": [0.9, 0.1, 0.1, 0.1],
         "payload": {"chunk_id": "c1", "document_id": "d1", "page": 1,
                     "section_title": "S1", "text": "personvern og databehandling"}},
        {"id": "c2", "dense": [0.1, 0.9, 0.1, 0.1],
         "payload": {"chunk_id": "c2", "document_id": "d2", "page": 2,
                     "section_title": "S2", "text": "risikovurdering av systemer"}},
    ]
    await upsert_chunks(client, project_id=project_id, points=points)

    yield client, project_id

    await client.delete_collection(coll)
    await client.close()


@pytest.mark.asyncio
async def test_dense_query_returns_relevant_chunk(qdrant_with_data):
    """Dense-only path: a vector close to c1 returns c1 first."""
    client, project_id = qdrant_with_data
    results = await hybrid_query(
        client, project_id=project_id,
        query_text="zzzznomatch",  # won't BM25-match c1's text
        query_vector=[0.95, 0.05, 0.1, 0.1],
        limit=5,
    )
    assert len(results) >= 1
    assert results[0]["chunk_id"] == "c1"
    assert results[0]["text"] == "personvern og databehandling"


@pytest.mark.asyncio
async def test_bm25_query_returns_lexical_match(qdrant_with_data):
    """BM25 path: a string query matches the chunk containing that word.

    Uses a zero vector for dense so any result must come from BM25.
    """
    client, project_id = qdrant_with_data
    results = await hybrid_query(
        client, project_id=project_id,
        query_text="risikovurdering",
        query_vector=[0.0, 0.0, 0.0, 0.0],  # dense contributes nothing
        limit=5,
    )
    chunk_ids = [r["chunk_id"] for r in results]
    assert "c2" in chunk_ids


@pytest.mark.asyncio
async def test_hybrid_results_carry_citation_provenance(qdrant_with_data):
    """Each result must carry document_id + page for [doc, page] citations (§451)."""
    client, project_id = qdrant_with_data
    results = await hybrid_query(
        client, project_id=project_id,
        query_text="personvern",
        query_vector=[0.9, 0.1, 0.1, 0.1],
        limit=5,
    )
    assert results
    for r in results:
        assert "document_id" in r
        assert "page" in r
        assert "text" in r
