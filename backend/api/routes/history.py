"""
Chat History API routes.

POST   /api/v1/history/        — save a conversation (create or update)
GET    /api/v1/history/        — list saved conversations (newest first)
GET    /api/v1/history/{id}    — get full conversation
DELETE /api/v1/history/{id}    — delete a conversation
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.chat_history_service import chat_history_service

router = APIRouter()


class SaveChatRequest(BaseModel):
    messages: list[dict]
    model: str = ""
    chat_id: str | None = None


@router.post("/")
async def save_chat(req: SaveChatRequest) -> dict:
    record = chat_history_service.save(req.messages, req.model, req.chat_id)
    return {"id": record.id, "title": record.title}


@router.get("/")
async def list_chats() -> dict:
    return {"chats": chat_history_service.list_all()}


@router.get("/{chat_id}")
async def get_chat(chat_id: str) -> dict:
    record = chat_history_service.get(chat_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return record


@router.delete("/{chat_id}")
async def delete_chat(chat_id: str) -> dict:
    if not chat_history_service.delete(chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"success": True, "id": chat_id}
