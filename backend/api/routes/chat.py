"""
Chat API routes.

POST /api/v1/chat/complete     — standard completion
POST /api/v1/chat/stream       — server-sent events streaming
POST /api/v1/chat/excel        — process Excel files with AI
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.models.chat import ChatRequest, ChatResponse, ExcelChatRequest
from backend.services.ai.base import CompletionRequest, Message
from backend.services.ai.router import ai_router
from backend.services.excel_service import excel_service
from backend.services.file_service import file_service
from backend.services.result_service import result_service
from backend.services.remote.gpu_executor import gpu_executor
from backend.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter()


def _to_service_messages(messages: list) -> list[Message]:
    return [Message(role=m.role, content=m.content) for m in messages]


@router.post("/complete", response_model=ChatResponse)
async def chat_complete(req: ChatRequest) -> ChatResponse:
    request = CompletionRequest(
        messages=_to_service_messages(req.messages),
        model=req.model,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
    )
    try:
        resp = await ai_router.complete(request)
    except Exception as e:
        log.error("Chat completion failed", error=str(e))
        raise HTTPException(status_code=502, detail=str(e))

    saved_path = None
    if req.save_result and req.messages:
        user_prompt = next(
            (m.content for m in reversed(req.messages) if m.role == "user"), ""
        )
        path = result_service.save_markdown(
            prompt=user_prompt,
            response=resp.content,
            model=resp.model,
            title=req.result_title,
        )
        saved_path = str(path)

    return ChatResponse(
        content=resp.content,
        model=resp.model,
        provider=resp.provider,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        finish_reason=resp.finish_reason,
        saved_path=saved_path,
    )


@router.post("/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    request = CompletionRequest(
        messages=_to_service_messages(req.messages),
        model=req.model,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        stream=True,
    )

    async def generate():
        async for chunk in ai_router.stream(request):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/excel")
async def excel_chat(req: ExcelChatRequest) -> dict:
    """
    Process uploaded Excel files using a natural-language prompt.
    Returns the AI-generated code, explanation, and download info.
    """
    # Resolve file paths
    paths = []
    for fid in req.file_ids:
        path = file_service.get_path(fid)
        if path is None:
            raise HTTPException(status_code=404, detail=f"File {fid} not found")
        paths.append(path)

    if req.executor == "gpu":
        if not gpu_executor.is_configured:
            raise HTTPException(status_code=400, detail="GPU server not configured")
        # For GPU: ship the code to remote; simplified — full impl sends serialised frames
        result = await excel_service.process(paths, req.prompt, req.model)
    elif req.executor == "spark":
        from backend.services.remote.spark_executor import spark_executor
        if not spark_executor.is_configured:
            raise HTTPException(status_code=400, detail="Spark not configured")
        result = await excel_service.process(paths, req.prompt, req.model)
    else:
        result = await excel_service.process(paths, req.prompt, req.model)

    response: dict = {
        "code": result["code"],
        "explanation": result["explanation"],
        "error": result["error"],
        "result_shape": None,
        "saved_excel": None,
        "saved_markdown": None,
    }

    df = result["result_df"]
    if df is not None:
        response["result_shape"] = {"rows": len(df), "cols": len(df.columns)}
        response["result_preview"] = df.head(20).to_dict(orient="records")

        if req.save_result:
            xlsx_path = result_service.save_excel(df, label=req.prompt[:30])
            md_path = result_service.save_markdown(
                prompt=req.prompt,
                response=f"**Code:**\n```python\n{result['code']}\n```\n\n**Explanation:** {result['explanation']}",
                model=req.model,
            )
            response["saved_excel"] = str(xlsx_path)
            response["saved_markdown"] = str(md_path)

    return response
