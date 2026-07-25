from __future__ import annotations

import logging
from app.ai.providers.openrouter import OpenRouterClient
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_BATCH = 64

async def embed_chunk(texts: list[str], or_client: OpenRouterClient) -> list[list[float]]:
    """
        Embed chunk texts in batches and assert every vector matches the configuration dim.

        Dim assertion is the embedding-drift invariant. If Openrouter silently swaps the model,
        vectors would still index but recall would corrupt. This will make it fail loudly so
        the wrong dim vectors doesn't get indexed
    """

    settings = get_settings()
    expected = settings.embed_dim
    out: list[list[float]] = []

    for i in range(0, len(texts), _BATCH):
        batch = texts[i : i + _BATCH]
        vectors = await or_client.embed(batch)
        for v in vectors:
            if len(v) != expected:
                raise RuntimeError(
                    f"embedding dim drigt: got {len(v)}, {expected}"
                    f"(model={settings.embed_model}), refusing to index"
                )
        out.extend(vectors)
    return out
