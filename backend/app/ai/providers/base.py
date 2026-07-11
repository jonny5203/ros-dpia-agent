"""Provider abstractions.

One `LLMClient` over OpenRouter for the MVP (chat + embeddings). A local
Ollama backend is a post-MVP roadmap item (R7) and will implement the same
protocols, so callers stay provider-agnostic.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        ...


@runtime_checkable
class ChatClient(Protocol):
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        ...
