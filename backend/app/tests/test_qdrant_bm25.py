"""Integration test: server-side BM25 contract (1.13+ shape).

Locks the contract that:
- We declare a payload text index with modifier=IDF
- We query with a raw string, using="bm25"
- Qdrant tokenizes payload.text server-side and returns matches

Marked `slow` because it needs a live Qdrant instance.
Set QDRANT_URL env var to point at it (default: localhost:6333).
"""

from __future__ import annotations

import os
import uuid

import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

pytestmark = pytest.mark.slow


@pytest.fixture
async def qdrant():
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    client = AsyncQdrantClient(url=url)
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_server_side_bm25_returns_match(qdrant):
    """String query via using='bm25' returns the matching payload."""
    coll = f"test_bm25_{uuid.uuid4().hex[:8]}"
    try:
        await qdrant.create_collection(
            collection_name=coll,
            vectors_config={"dense": qm.VectorParams(size=4, distance=qm.Distance.COSINE)},
            sparse_vectors_config={
                "bm25": qm.SparseVectorParams(index=qm.SparseIndexParams())
            },
        )
        await qdrant.create_payload_index(
            collection_name=coll,
            field_name="text",
            field_schema=qm.TextIndexParams(
                type="text",
                tokenizer=qm.TokenizerType.WORD,
                lowercase=True,
                modifier=qm.TranslationModifier.IDF,
            ),
        )
        await qdrant.upsert(collection_name=coll, points=[
            qm.PointStruct(
                id="1",
                vector={"dense": [0.1, 0.2, 0.3, 0.4]},
                payload={"text": "personvern i kommunen"},
            ),
        ])

        resp = await qdrant.query_points(
            collection_name=coll,
            prefetch=[qm.Prefetch(query="personvern", using="bm25", limit=10)],
            limit=10,
            with_payload=True,
        )
        assert len(resp.points) == 1
        assert resp.points[0].payload["text"] == "personvern i kommunen"
    finally:
        await qdrant.delete_collection(coll)


@pytest.mark.asyncio
async def test_bm25_returns_empty_when_no_match(qdrant):
    """A query with no lexical overlap returns no results from the BM25 leg."""
    coll = f"test_bm25_nomatch_{uuid.uuid4().hex[:8]}"
    try:
        await qdrant.create_collection(
            collection_name=coll,
            vectors_config={"dense": qm.VectorParams(size=4, distance=qm.Distance.COSINE)},
            sparse_vectors_config={"bm25": qm.SparseVectorParams(index=qm.SparseIndexParams())},
        )
        await qdrant.create_payload_index(
            collection_name=coll, field_name="text",
            field_schema=qm.TextIndexParams(
                type="text", tokenizer=qm.TokenizerType.WORD,
                lowercase=True, modifier=qm.TranslationModifier.IDF,
            ),
        )
        await qdrant.upsert(collection_name=coll, points=[
            qm.PointStruct(id="1", vector={"dense": [0.1, 0.2, 0.3, 0.4]},
                           payload={"text": " completely different vocabulary"}),
        ])

        resp = await qdrant.query_points(
            collection_name=coll,
            prefetch=[qm.Prefetch(query="personvern", using="bm25", limit=10)],
            limit=10,
            with_payload=True,
        )
        assert len(resp.points) == 0
    finally:
        await qdrant.delete_collection(coll)
