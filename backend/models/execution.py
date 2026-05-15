"""Pydantic schemas for execution and model management APIs."""
from typing import Literal
from pydantic import BaseModel


class ModelPullRequest(BaseModel):
    model: str


class ModelDeleteRequest(BaseModel):
    model: str


class ModelInfo(BaseModel):
    name: str
    provider: str
    available: bool = True


class AllModelsResponse(BaseModel):
    openai: list[str]
    gemini: list[str]
    ollama: list[str]


class HealthResponse(BaseModel):
    openai: bool
    gemini: bool
    ollama: bool


class GPUJobRequest(BaseModel):
    code: str
    context: dict = {}


class GPUJobResponse(BaseModel):
    job_id: str
    status: Literal["done", "error", "pending"]
    result: str = ""
    error: str = ""


class ResultItem(BaseModel):
    filename: str
    path: str
    size_kb: float
    modified: str
