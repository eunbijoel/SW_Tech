"""
AI model router — selects the correct provider at runtime.

Usage:
    router = AIRouter()
    response = await router.complete(request)

Provider is determined by request.model prefix:
    gpt-*        → OpenAI
    gemini-*     → Gemini
    anything else → Ollama (local)
"""
from typing import AsyncGenerator

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.services.ai.base import BaseAIService, CompletionRequest, CompletionResponse
from backend.services.ai.openai_service import OpenAIService
from backend.services.ai.gemini_service import GeminiService
from backend.services.ai.ollama_service import OllamaService

log = get_logger(__name__)

PROVIDER_OPENAI = "openai"
PROVIDER_GEMINI = "gemini"
PROVIDER_OLLAMA = "ollama"


class AIRouter:
    """
    Routes completion requests to the correct AI provider.
    Instances are created once and reused (services are stateless).
    """

    def __init__(self) -> None:
        self._services: dict[str, BaseAIService] = {
            PROVIDER_OPENAI: OpenAIService(),
            PROVIDER_GEMINI: GeminiService(),
            PROVIDER_OLLAMA: OllamaService(),
        }

    def _resolve_provider(self, model: str) -> str:
        if not model:
            return PROVIDER_OPENAI
        model_lower = model.lower()
        if model_lower.startswith("gpt") or model_lower.startswith("o1"):
            return PROVIDER_OPENAI
        if model_lower.startswith("gemini"):
            return PROVIDER_GEMINI
        return PROVIDER_OLLAMA

    def get_service(self, provider: str) -> BaseAIService:
        svc = self._services.get(provider)
        if svc is None:
            raise ValueError(f"Unknown AI provider: {provider}")
        return svc

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        provider = self._resolve_provider(request.model)
        log.info("Routing to provider", provider=provider, model=request.model)
        return await self._services[provider].complete(request)

    async def stream(self, request: CompletionRequest) -> AsyncGenerator[str, None]:
        provider = self._resolve_provider(request.model)
        async for chunk in self._services[provider].stream(request):
            yield chunk

    async def list_all_models(self) -> dict[str, list[str]]:
        """Return available models per provider (best-effort)."""
        result: dict[str, list[str]] = {}
        for name, svc in self._services.items():
            try:
                result[name] = await svc.list_models()
            except Exception as e:
                log.warning("Failed to list models", provider=name, error=str(e))
                result[name] = []
        return result

    async def health(self) -> dict[str, bool]:
        result: dict[str, bool] = {}
        for name, svc in self._services.items():
            try:
                result[name] = await svc.health_check()
            except Exception:
                result[name] = False
        return result


# Module-level singleton — imported by route handlers
ai_router = AIRouter()
