"""Pydantic schemas for the chat API."""
from typing import Literal
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str = ""
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    stream: bool = False
    save_result: bool = False
    result_title: str = ""


class ChatResponse(BaseModel):
    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"
    saved_path: str | None = None


class ExcelChatRequest(BaseModel):
    file_ids: list[str] = Field(..., min_length=1)
    prompt: str
    model: str = ""
    executor: Literal["local", "gpu", "spark"] = "local"
    save_result: bool = True
