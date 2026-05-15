"""
Unit tests for AIRouter provider resolution logic (no network calls).
"""
import pytest

from backend.services.ai.router import AIRouter, PROVIDER_GEMINI, PROVIDER_OLLAMA, PROVIDER_OPENAI


@pytest.fixture
def router() -> AIRouter:
    return AIRouter()


@pytest.mark.parametrize(
    "model, expected",
    [
        ("gpt-4o", PROVIDER_OPENAI),
        ("gpt-3.5-turbo", PROVIDER_OPENAI),
        ("o1-preview", PROVIDER_OPENAI),
        ("GPT-4", PROVIDER_OPENAI),         # case-insensitive
        ("gemini-1.5-pro", PROVIDER_GEMINI),
        ("gemini-2.0-flash", PROVIDER_GEMINI),
        ("GEMINI-PRO", PROVIDER_GEMINI),
        ("llama3", PROVIDER_OLLAMA),
        ("mistral", PROVIDER_OLLAMA),
        ("phi3:mini", PROVIDER_OLLAMA),
        ("codellama:13b", PROVIDER_OLLAMA),
        ("", PROVIDER_OPENAI),              # empty → default
    ],
)
def test_provider_resolution(router: AIRouter, model: str, expected: str) -> None:
    assert router._resolve_provider(model) == expected


def test_get_service_openai(router: AIRouter) -> None:
    from backend.services.ai.openai_service import OpenAIService
    svc = router.get_service(PROVIDER_OPENAI)
    assert isinstance(svc, OpenAIService)


def test_get_service_gemini(router: AIRouter) -> None:
    from backend.services.ai.gemini_service import GeminiService
    svc = router.get_service(PROVIDER_GEMINI)
    assert isinstance(svc, GeminiService)


def test_get_service_ollama(router: AIRouter) -> None:
    from backend.services.ai.ollama_service import OllamaService
    svc = router.get_service(PROVIDER_OLLAMA)
    assert isinstance(svc, OllamaService)


def test_get_service_unknown(router: AIRouter) -> None:
    with pytest.raises(ValueError, match="Unknown AI provider"):
        router.get_service("does-not-exist")
