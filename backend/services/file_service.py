"""
File management service.
Handles upload storage, metadata, listing, and deletion.
Files are stored with UUID names; metadata is kept in a sidecar .json.
Library files (excel/ directory) are read-only — they appear in listings
but are never moved or deleted.
"""
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import aiofiles

from backend.core.config import settings
from backend.core.logging import get_logger

log = get_logger(__name__)

_LIBRARY_SESSION = "__library__"


@dataclass
class FileRecord:
    id: str
    original_name: str
    stored_name: str        # relative to UPLOAD_DIR for uploads; absolute for library files
    extension: str
    size_bytes: int
    uploaded_at: str
    session_id: str = ""
    tags: list[str] = field(default_factory=list)
    library: bool = False   # True → file lives in EXCEL_LIBRARY_DIR, not in uploads

    @property
    def path(self) -> Path:
        if self.library:
            return Path(self.stored_name)
        return settings.UPLOAD_DIR / self.stored_name

    @property
    def meta_path(self) -> Path:
        return settings.UPLOAD_DIR / f"{self.id}.json"


def _library_file_id(path: Path) -> str:
    """Stable, deterministic UUID derived from the file name so IDs survive restarts."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"library://{path.name}"))


class FileService:
    def __init__(self) -> None:
        self._upload_dir = settings.UPLOAD_DIR
        self._library_dir = settings.EXCEL_LIBRARY_DIR

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_meta(self, file_id: str) -> FileRecord | None:
        meta_path = self._upload_dir / f"{file_id}.json"
        if not meta_path.exists():
            return None
        with meta_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return FileRecord(**data)

    def _save_meta(self, record: FileRecord) -> None:
        with record.meta_path.open("w", encoding="utf-8") as f:
            json.dump(asdict(record), f, ensure_ascii=False, indent=2)

    def _make_library_record(self, path: Path) -> FileRecord:
        return FileRecord(
            id=_library_file_id(path),
            original_name=path.name,
            stored_name=str(path.resolve()),
            extension=path.suffix.lstrip(".").lower(),
            size_bytes=path.stat().st_size,
            uploaded_at=datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
            session_id=_LIBRARY_SESSION,
            library=True,
        )

    # ── Upload ────────────────────────────────────────────────────────────────

    async def save_upload(
        self,
        filename: str,
        content: bytes,
        session_id: str = "",
    ) -> FileRecord:
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext not in settings.allowed_extensions_set:
            raise ValueError(f"Extension '.{ext}' is not allowed")
        if len(content) > settings.max_upload_bytes:
            raise ValueError(f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit")

        file_id = str(uuid.uuid4())
        stored_name = f"{file_id}.{ext}"
        dest = self._upload_dir / stored_name

        async with aiofiles.open(dest, "wb") as f:
            await f.write(content)

        record = FileRecord(
            id=file_id,
            original_name=filename,
            stored_name=stored_name,
            extension=ext,
            size_bytes=len(content),
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
        )
        self._save_meta(record)
        log.info("File uploaded", file_id=file_id, name=filename, size=len(content))
        return record

    # ── Library ───────────────────────────────────────────────────────────────

    def list_library_files(self) -> list[FileRecord]:
        """Return read-only Excel files from the EXCEL_LIBRARY_DIR folder."""
        if not self._library_dir.exists():
            return []
        records: list[FileRecord] = []
        for p in sorted(self._library_dir.iterdir()):
            if p.suffix.lower() in {".xlsx", ".xls", ".csv"} and p.is_file():
                try:
                    records.append(self._make_library_record(p))
                except Exception as e:
                    log.warning("Failed to read library file", path=str(p), error=str(e))
        return records

    def get_library_file(self, file_id: str) -> FileRecord | None:
        for rec in self.list_library_files():
            if rec.id == file_id:
                return rec
        return None

    # ── Query ─────────────────────────────────────────────────────────────────

    def list_files(self, session_id: str = "") -> list[FileRecord]:
        """List uploaded files (excludes library files)."""
        records = []
        for meta in self._upload_dir.glob("*.json"):
            try:
                with meta.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                rec = FileRecord(**data)
                if session_id and rec.session_id != session_id:
                    continue
                records.append(rec)
            except Exception as e:
                log.warning("Failed to load file meta", path=str(meta), error=str(e))
        return sorted(records, key=lambda r: r.uploaded_at, reverse=True)

    def get_file(self, file_id: str) -> FileRecord | None:
        record = self._load_meta(file_id)
        if record:
            return record
        return self.get_library_file(file_id)

    def delete_file(self, file_id: str) -> bool:
        record = self._load_meta(file_id)
        if record is None:
            return False
        if record.library:
            log.warning("Attempted to delete library file — rejected", file_id=file_id)
            return False
        try:
            record.path.unlink(missing_ok=True)
            record.meta_path.unlink(missing_ok=True)
            log.info("File deleted", file_id=file_id)
            return True
        except Exception as e:
            log.error("Delete failed", file_id=file_id, error=str(e))
            return False

    def get_path(self, file_id: str) -> Path | None:
        """Resolve a file_id to its filesystem path (uploaded or library)."""
        # 1. Try uploaded files
        record = self._load_meta(file_id)
        if record and record.path.exists():
            return record.path
        # 2. Try library files
        lib = self.get_library_file(file_id)
        if lib and lib.path.exists():
            return lib.path
        return None


file_service = FileService()
