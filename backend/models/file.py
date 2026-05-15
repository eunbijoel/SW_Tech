"""Pydantic schemas for the files API."""
from pydantic import BaseModel


class FileInfo(BaseModel):
    id: str
    original_name: str
    extension: str
    size_bytes: int
    uploaded_at: str
    session_id: str = ""
    library: bool = False


class FileListResponse(BaseModel):
    files: list[FileInfo]
    total: int


class DeleteResponse(BaseModel):
    success: bool
    file_id: str
