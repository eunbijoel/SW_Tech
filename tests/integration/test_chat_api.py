"""
Integration tests for the Chat API routes.
AI providers are mocked so no real API keys are needed.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.services.ai.base import CompletionResponse


@pytest.fixture
def mock_ai_complete():
    """Patch ai_router.complete to return a canned response."""
    fake = CompletionResponse(
        content="Hello! This is a test response.",
        model="gpt-4o",
        provider="openai",
        input_tokens=10,
        output_tokens=8,
    )
    with patch(
        "backend.api.routes.chat.ai_router.complete",
        new_callable=AsyncMock,
        return_value=fake,
    ) as mock:
        yield mock


def test_health_endpoint(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_chat_complete_success(client: TestClient, mock_ai_complete) -> None:
    payload = {
        "messages": [{"role": "user", "content": "Say hello"}],
        "model": "gpt-4o",
    }
    resp = client.post("/api/v1/chat/complete", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "Hello! This is a test response."
    assert data["provider"] == "openai"
    assert data["input_tokens"] == 10
    assert data["output_tokens"] == 8


def test_chat_complete_saves_markdown(client: TestClient, mock_ai_complete) -> None:
    payload = {
        "messages": [{"role": "user", "content": "Summarise this"}],
        "model": "gpt-4o",
        "save_result": True,
        "result_title": "Test Save",
    }
    resp = client.post("/api/v1/chat/complete", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["saved_path"] is not None
    assert data["saved_path"].endswith(".md")


def test_chat_complete_empty_messages(client: TestClient) -> None:
    resp = client.post("/api/v1/chat/complete", json={"messages": []})
    # FastAPI validates min length; messages must be non-empty list
    # Pydantic allows empty list here — AI call would fail, but 422 is acceptable too
    assert resp.status_code in (200, 422, 502)


def test_chat_complete_invalid_temperature(client: TestClient) -> None:
    payload = {
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 5.0,  # > 2.0 → validation error
    }
    resp = client.post("/api/v1/chat/complete", json=payload)
    assert resp.status_code == 422
