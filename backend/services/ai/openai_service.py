"""
OpenAI provider adapter.
Supports GPT-4o, GPT-4-turbo, GPT-3.5-turbo, and any future chat model.
"""
from typing import AsyncGenerator

from openai import AsyncOpenAI, APIConnectionError, AuthenticationError

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.services.ai.base import (
    BaseAIService,
    CompletionRequest,
    CompletionResponse,
    Message,
)

log = get_logger(__name__)

ROLE_MAP = {"system": "system", "user": "user", "assistant": "assistant"}


class OpenAIService(BaseAIService):
    provider_name = "openai"

    def __init__(self, api_key: str | None = None) -> None:
        self._client = AsyncOpenAI(api_key=api_key or settings.OPENAI_API_KEY)

    def _build_messages(self, messages: list[Message]) -> list[dict]:
        return [{"role": ROLE_MAP[m.role], "content": m.content} for m in messages]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        model = request.model or settings.OPENAI_DEFAULT_MODEL
        log.info("OpenAI complete", model=model)
        try:
            resp = await self._client.chat.completions.create(
                model=model,
                messages=self._build_messages(request.messages),
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                stream=False,
            )
            choice = resp.choices[0]
            return CompletionResponse(
                content=choice.message.content or "",
                model=resp.model,
                provider=self.provider_name,
                input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                output_tokens=resp.usage.completion_tokens if resp.usage else 0,
                finish_reason=choice.finish_reason or "stop",
            )
        except AuthenticationError as e:
            log.error("OpenAI auth failed", error=str(e))
            raise ValueError("Invalid OpenAI API key") from e
        except APIConnectionError as e:
            log.error("OpenAI connection error", error=str(e))
            raise ConnectionError("Cannot reach OpenAI API") from e

    async def stream(self, request: CompletionRequest) -> AsyncGenerator[str, None]:
        model = request.model or settings.OPENAI_DEFAULT_MODEL
        log.info("OpenAI stream", model=model)
        async with await self._client.chat.completions.create(
            model=model,
            messages=self._build_messages(request.messages),
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            stream=True,
        ) as resp:
            async for chunk in resp:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

    async def list_models(self) -> list[str]:
        try:
            page = await self._client.models.list()
            return sorted(
                m.id for m in page.data if "gpt" in m.id
            )
        except Exception:
            return [settings.OPENAI_DEFAULT_MODEL]

    async def health_check(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False
