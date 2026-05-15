"""
Abstract AI provider interface.

Every AI backend (OpenAI, Gemini, Ollama …) must implement this contract.
The router picks the correct implementation at runtime — callers never
depend on a concrete class.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator


@dataclass
class Message:
    role: str          # "system" | "user" | "assistant"
    content: str


@dataclass
class CompletionRequest:
    messages: list[Message]
    model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.2
    stream: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class CompletionResponse:
    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"


class BaseAIService(ABC):
    """
    All concrete AI service classes must subclass this.
    Implement complete() for standard calls and stream() for SSE/streaming.
    """

    provider_name: str = "base"

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Return a full completion response (non-streaming)."""

    @abstractmethod
    async def stream(self, request: CompletionRequest) -> AsyncGenerator[str, None]:
        """Yield response chunks one at a time (streaming)."""
        # pragma: no cover — force subclasses to implement
        yield ""

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return available model names for this provider."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable."""
