"""
Model management API routes.

GET    /api/v1/models/           — list all models from all providers
GET    /api/v1/models/health     — provider health check
POST   /api/v1/models/pull       — pull/download an Ollama model
DELETE /api/v1/models/{model}    — delete an Ollama model
GET    /api/v1/models/{model}/info — model details
GET    /api/v1/results/          — list saved results
GET    /api/v1/results/{type}/{filename} — get result content
DELETE /api/v1/results/{type}/{filename} — delete a result
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.models.execution import (
    AllModelsResponse,
    HealthResponse,
    ModelPullRequest,
    ModelDeleteRequest,
    ResultItem,
)
from backend.services.ai.router import ai_router
from backend.services.ai.ollama_service import OllamaService
from backend.services.result_service import result_service
from backend.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter()

_ollama = OllamaService()


@router.get("/", response_model=AllModelsResponse)
async def list_models() -> AllModelsResponse:
    all_models = await ai_router.list_all_models()
    return AllModelsResponse(
        openai=all_models.get("openai", []),
        gemini=all_models.get("gemini", []),
        ollama=all_models.get("ollama", []),
    )


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    health = await ai_router.health()
    return HealthResponse(
        openai=health.get("openai", False),
        gemini=health.get("gemini", False),
        ollama=health.get("ollama", False),
    )


@router.post("/pull")
async def pull_model(req: ModelPullRequest) -> StreamingResponse:
    """Stream Ollama model download progress."""
    async def generate():
        async for status in _ollama.pull_model(req.model):
            yield f"data: {status}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.delete("/{model}")
async def delete_model(model: str) -> dict:
    success = await _ollama.delete_model(model)
    if not success:
        raise HTTPException(status_code=404, detail=f"Model {model} not found")
    return {"success": True, "model": model}


@router.get("/{model}/info")
async def model_info(model: str) -> dict:
    try:
        return await _ollama.model_info(model)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Results management ────────────────────────────────────────────────────────

@router.get("/results/list")
async def list_results(result_type: str = "all") -> dict:
    return result_service.list_results(result_type)


@router.get("/results/{result_type}/{filename}")
async def get_result(result_type: str, filename: str) -> dict:
    if result_type != "markdown":
        raise HTTPException(status_code=400, detail="Only markdown preview supported via API")
    content = result_service.read_markdown(filename)
    if content is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return {"filename": filename, "content": content}


@router.delete("/results/{result_type}/{filename}")
async def delete_result(result_type: str, filename: str) -> dict:
    success = result_service.delete_result(result_type, filename)
    if not success:
        raise HTTPException(status_code=404, detail="Result not found")
    return {"success": True}
