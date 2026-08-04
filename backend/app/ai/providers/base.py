"""Provider abstractions for chat, structured output, and embeddings."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)


@runtime_checkable
class EmbeddingClient(Protocol):
    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]: ...


@runtime_checkable
class ChatClient(Protocol):
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...


@runtime_checkable
class StructuredChatClient(Protocol):
    async def structured_completion(
        self,
        messages: list[dict[str, str]],
        *,
        response_model: type[TModel],
        model: str | None = None,
        max_retries: int = 2,
        **kwargs: Any,
    ) -> TModel: ...


class ProfileAIClient(EmbeddingClient, StructuredChatClient, Protocol):
    """Capabilities required by profile extraction."""
