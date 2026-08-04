from __future__ import annotations

import logging

from app.ai.providers.base import EmbeddingClient
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_BATCH = 64


async def embed_chunks(
    texts: list[str],
    client: EmbeddingClient,
) -> list[list[float]]:
    """Embed text in batches and reject unexpected vector dimensions."""

    settings = get_settings()
    expected = settings.embed_dim
    output: list[list[float]] = []

    for index in range(0, len(texts), _BATCH):
        batch = texts[index : index + _BATCH]
        vectors = await client.embed(batch)
        for vector in vectors:
            if len(vector) != expected:
                raise RuntimeError(
                    f"embedding dimension drift: got {len(vector)}, "
                    f"expected {expected} "
                    f"(model={settings.embed_model})"
                )
        output.extend(vectors)

    return output
