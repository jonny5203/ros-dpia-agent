from __future__ import annotations

import logging
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

logger = logging.getLogger(__name__)

def collection_name(project_id) -> str:
    return f"chunks_{project_id}"

async def upsert_chunks(
    qdrant: AsyncQdrantClient,
    *,
    project_id,
    points: list[dict[str, Any]],
) -> None:
    """
        Upsert pre-computed (dense, sparse, payload) points.

        Each point id is the chunk's uuid5 (string -> uuid for Qdrant) so re-upserts
        overwrite the same points -> idempotent re-indexing.
    """

    coll = collection_name(project_id)
    qpoints = [
        qm.PointStruct(
            id=str(p["id"]),
            vector={"dense": p["dense"]},
            payload=p["payload"]
        )
        for p in points
    ]

    await qdrant.upsert(collection_name=coll, points=qpoints)

async def hybrid_query(
    qdrant: AsyncQdrantClient,
    *,
    project_id,
    query_text: str,
    query_vector: list[float],
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
        Hybrid dense + server-side BM25 query fused by RRF, scoped to one project.
    """
    coll = collection_name(project_id)
    resp = await qdrant.query_points(
        collection_name=coll,
        prefetch=[
            qm.Prefetch(query=query_vector, using="dense", limit=limit * 3),
            qm.Prefetch(query=query_text, using="bm25", limit=limit * 3),
        ],
        query=qm.FusionQuery(fusion=qm.Fusion.RRF),
        limit=limit,
        with_payload=True,
    )

    results: list[dict[str, Any]] = []
    for point in resp.points:
        payload = point.payload or {}
        results.append(
            {
                "chunk_id": payload.get("chunk_id"),
                "document_id": payload.get("document_id"),
                "page": payload.get("page"),
                "section_title": payload.get("section_title"),
                "text": payload.get("text"),
                "score": point.score,
            }
        )
    return results
