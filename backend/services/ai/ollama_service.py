"""
Ollama local model provider adapter.
Communicates with the Ollama HTTP server (default: http://localhost:11434).
Supports model download/pull and execution management.
"""
from typing import AsyncGenerator

import httpx

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.services.ai.base import (
    BaseAIService,
    CompletionRequest,
    CompletionResponse,
    Message,
)

log = get_logger(__name__)


def _build_ollama_messages(messages: list[Message]) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in messages]


class OllamaService(BaseAIService):
    provider_name = "ollama"

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=300)

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        model = request.model or settings.OLLAMA_DEFAULT_MODEL
        log.info("Ollama complete", model=model)
        payload = {
            "model": model,
            "messages": _build_ollama_messages(request.messages),
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        async with self._client() as client:
            resp = await client.post("/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return CompletionResponse(
            content=data["message"]["content"],
            model=model,
            provider=self.provider_name,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
        )

    async def stream(self, request: CompletionRequest) -> AsyncGenerator[str, None]:
        import json as _json

        model = request.model or settings.OLLAMA_DEFAULT_MODEL
        payload = {
            "model": model,
            "messages": _build_ollama_messages(request.messages),
            "stream": True,
            "options": {"temperature": request.temperature},
        }
        async with self._client() as client:
            async with client.stream("POST", "/api/chat", json=payload) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = _json.loads(line)
                        if content := chunk.get("message", {}).get("content"):
                            yield content
                    except Exception:
                        continue

    async def list_models(self) -> list[str]:
        try:
            async with self._client() as client:
                resp = await client.get("/api/tags")
                resp.raise_for_status()
                data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    async def health_check(self) -> bool:
        try:
            async with self._client() as client:
                resp = await client.get("/api/tags", timeout=5)
                return resp.status_code == 200
        except Exception:
            return False

    # ── Model management ──────────────────────────────────────────────────────

    async def pull_model(self, model: str) -> AsyncGenerator[str, None]:
        """Stream pull progress from Ollama."""
        import json as _json

        async with self._client() as client:
            async with client.stream(
                "POST", "/api/pull", json={"name": model, "stream": True}
            ) as resp:
                async for line in resp.aiter_lines():
                    if line:
                        try:
                            yield _json.loads(line).get("status", "")
                        except Exception:
                            continue

    async def delete_model(self, model: str) -> bool:
        async with self._client() as client:
            resp = await client.delete("/api/delete", json={"name": model})
            return resp.status_code == 200

    async def model_info(self, model: str) -> dict:
        async with self._client() as client:
            resp = await client.post("/api/show", json={"name": model})
            resp.raise_for_status()
            return resp.json()
