"""LLM provider implementations. OpenRouter is the sole MVP backend; a local
Ollama backend lands in roadmap item R7.
"""

from app.ai.providers.openrouter import OpenRouterClient, OpenRouterError

__all__ = ["OpenRouterClient", "OpenRouterError"]
