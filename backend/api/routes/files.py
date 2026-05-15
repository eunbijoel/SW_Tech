"""
Files API routes.

POST   /api/v1/files/upload          — upload one or more Excel/CSV files
GET    /api/v1/files/                — list uploaded files
GET    /api/v1/files/library         — list pre-seeded library files (excel/ dir)
GET    /api/v1/files/{file_id}       — get file metadata (upload or library)
DELETE /api/v1/files/{file_id}       — delete an uploaded file (library files rejected)
GET    /api/v1/files/{file_id}/download — download raw file bytes
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from backend.models.file import FileInfo, FileListResponse, DeleteResponse
from backend.services.file_service import file_service
from backend.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter()


def _record_to_info(record) -> FileInfo:
    return FileInfo(
        id=record.id,
        original_name=record.original_name,
        extension=record.extension,
        size_bytes=record.size_bytes,
        uploaded_at=record.uploaded_at,
        session_id=record.session_id,
        library=record.library,
    )


@router.post("/upload", response_model=list[FileInfo])
async def upload_files(
    files: list[UploadFile] = File(...),
    session_id: str = Form(default=""),
) -> list[FileInfo]:
    results = []
    for upload in files:
        content = await upload.read()
        try:
            record = await file_service.save_upload(
                filename=upload.filename or "unnamed",
                content=content,
                session_id=session_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        results.append(_record_to_info(record))
    return results


@router.get("/library", response_model=FileListResponse)
async def list_library_files() -> FileListResponse:
    """Return pre-seeded Excel files from the excel/ library directory."""
    records = file_service.list_library_files()
    items = [_record_to_info(r) for r in records]
    return FileListResponse(files=items, total=len(items))


@router.get("/", response_model=FileListResponse)
async def list_files(session_id: str = "") -> FileListResponse:
    records = file_service.list_files(session_id=session_id)
    return FileListResponse(files=[_record_to_info(r) for r in records], total=len(records))


@router.get("/{file_id}", response_model=FileInfo)
async def get_file(file_id: str) -> FileInfo:
    record = file_service.get_file(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    return _record_to_info(record)


@router.delete("/{file_id}", response_model=DeleteResponse)
async def delete_file(file_id: str) -> DeleteResponse:
    record = file_service.get_file(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    if record.library:
        raise HTTPException(status_code=403, detail="Library files cannot be deleted")
    success = file_service.delete_file(file_id)
    if not success:
        raise HTTPException(status_code=500, detail="Delete failed")
    return DeleteResponse(success=True, file_id=file_id)


@router.get("/{file_id}/download")
async def download_file(file_id: str) -> FileResponse:
    record = file_service.get_file(file_id)
    if record is None or not record.path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path=str(record.path),
        filename=record.original_name,
        media_type="application/octet-stream",
    )
