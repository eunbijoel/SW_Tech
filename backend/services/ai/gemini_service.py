"""
Google Gemini provider adapter.
Supports gemini-1.5-pro, gemini-1.5-flash, gemini-2.0-flash, etc.
"""
from typing import AsyncGenerator

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.services.ai.base import (
    BaseAIService,
    CompletionRequest,
    CompletionResponse,
    Message,
)

log = get_logger(__name__)

AVAILABLE_MODELS = [
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-thinking-exp",
]


def _to_gemini_history(messages: list[Message]) -> tuple[list[dict], str]:
    """Split messages into Gemini history format + final user turn."""
    history = []
    last_user = ""
    for m in messages:
        if m.role == "system":
            # Gemini has no explicit system role — prepend to first user message
            last_user = m.content
        elif m.role == "user":
            history.append({"role": "user", "parts": [last_user + m.content]})
            last_user = ""
        elif m.role == "assistant":
            history.append({"role": "model", "parts": [m.content]})

    # Last entry must be the user prompt
    if history and history[-1]["role"] == "user":
        final = history.pop()
        return history, final["parts"][0]
    return history, ""


class GeminiService(BaseAIService):
    provider_name = "gemini"

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or settings.GEMINI_API_KEY
        if key:
            genai.configure(api_key=key)
        self._api_key = key

    def _get_model(self, model_name: str) -> genai.GenerativeModel:
        return genai.GenerativeModel(model_name)

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        model_name = request.model or settings.GEMINI_DEFAULT_MODEL
        log.info("Gemini complete", model=model_name)
        try:
            history, prompt = _to_gemini_history(request.messages)
            model = self._get_model(model_name)
            chat = model.start_chat(history=history)
            resp = await chat.send_message_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=request.max_tokens,
                    temperature=request.temperature,
                ),
            )
            return CompletionResponse(
                content=resp.text,
                model=model_name,
                provider=self.provider_name,
            )
        except GoogleAPIError as e:
            log.error("Gemini API error", error=str(e))
            raise RuntimeError(f"Gemini error: {e}") from e

    async def stream(self, request: CompletionRequest) -> AsyncGenerator[str, None]:
        model_name = request.model or settings.GEMINI_DEFAULT_MODEL
        history, prompt = _to_gemini_history(request.messages)
        model = self._get_model(model_name)
        chat = model.start_chat(history=history)
        response = await chat.send_message_async(
            prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=request.max_tokens,
                temperature=request.temperature,
            ),
            stream=True,
        )
        async for chunk in response:
            if chunk.text:
                yield chunk.text

    async def list_models(self) -> list[str]:
        return AVAILABLE_MODELS

    async def health_check(self) -> bool:
        return bool(self._api_key)
