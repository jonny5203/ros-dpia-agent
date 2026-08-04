"""OpenRouter client — chat completions + embeddings over one OpenAI-compatible
gateway (https://openrouter.ai/api/v1).
"""

from __future__ import annotations

import logging
import time
from typing import Any, cast

import httpx
from instructor import AsyncInstructor, Mode, from_provider

from app.ai.providers.base import TModel
from app.core.config import Settings

logger = logging.getLogger(__name__)


class OpenRouterError(RuntimeError):
    """Raised when an OpenRouter call fails after retries."""


class OpenRouterClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.api_key = settings.openrouter_api_key_value
        self.default_chat_model = settings.llm_model
        self.default_embed_model = settings.embed_model
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers(),
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
        self._reach_cache: tuple[float, dict[str, Any]] | None = None
        self._structured_clients: dict[str, AsyncInstructor] = {}

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def close(self) -> None:
        structured_clients = tuple(self._structured_clients.values())
        self._structured_clients.clear()
        try:
            for client in structured_clients:
                underlying_client = client.client
                if underlying_client is not None:
                    await underlying_client.close()
        finally:
            await self._client.aclose()

    def _structured_client(self, model: str) -> AsyncInstructor:
        if not self.api_key:
            raise OpenRouterError("structured completion requires OPENROUTER_API_KEY")

        cached = self._structured_clients.get(model)
        if cached is not None:
            return cached

        created = from_provider(
            f"openrouter/{model}",
            async_client=True,
            api_key=self.api_key,
            base_url=self.base_url,
            mode=Mode.JSON_SCHEMA,
        )

        if not isinstance(created, AsyncInstructor):
            raise OpenRouterError("expected an asynchronous Instructor client")

        self._structured_clients[model] = created
        return created

    async def structured_completion(
        self,
        messages: list[dict[str, str]],
        *,
        response_model: type[TModel],
        model: str | None = None,
        max_retries: int = 2,
        **kwargs: Any,
    ) -> TModel:
        selected_model = model or self.default_chat_model
        client = self._structured_client(selected_model)

        try:
            result = await client.chat.completions.create(
                response_model=response_model,
                messages=cast(Any, messages),
                model=selected_model,
                max_retries=max_retries,
                strict=True,
                **kwargs,
            )
        except Exception as exc:
            raise OpenRouterError(
                f"structured completion failed for {response_model.__name__}"
            ) from exc

        if not isinstance(result, response_model):
            raise OpenRouterError(
                f"structured completion returned an invalid {response_model.__name__}"
            )

        return result

    # ── Reachability (used by /api/health) ───────────────────────────────
    async def reachability(self, *, cache_ttl: float = 30.0) -> dict[str, Any]:
        """Cheap liveness probe, cached to avoid hammering OpenRouter on each poll."""
        now = time.monotonic()
        if self._reach_cache and (now - self._reach_cache[0]) < cache_ttl:
            return self._reach_cache[1]
        result = await self._probe()
        self._reach_cache = (now, result)
        return result

    async def _probe(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "base_url": self.base_url,
            "key_configured": bool(self.api_key),
            "reachable": False,
            "key_valid": None,
        }
        # /models needs no auth — pure connectivity check.
        try:
            resp = await self._client.get("/models", timeout=httpx.Timeout(4.0))
            out["reachable"] = resp.is_success
            if resp.is_success:
                data = resp.json()
                out["model_count"] = len(data.get("data", [])) if isinstance(data, dict) else None
        except httpx.HTTPError as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"

        # /key validates the configured key (auth required). Skip if no key.
        if self.api_key:
            try:
                resp = await self._client.get("/key", timeout=httpx.Timeout(4.0))
                out["key_valid"] = resp.is_success
            except httpx.HTTPError as exc:
                out["key_valid"] = False
                out["key_error"] = type(exc).__name__
        return out

    # ── Embeddings ─────────────────────────────────────────────
    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": model or self.default_embed_model, "input": texts}
        resp = await self._client.post("/embeddings", json=payload)
        if resp.status_code >= 400:
            raise OpenRouterError(f"embeddings failed ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()["data"]
        data.sort(key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

    # ── Chat ──────────────────────────────────────────────────
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.default_chat_model,
            "messages": messages,
            **kwargs,
        }
        resp = await self._client.post("/chat/completions", json=payload)
        if resp.status_code >= 400:
            raise OpenRouterError(f"chat failed ({resp.status_code}): {resp.text[:200]}")
        return resp.json()
