"""
Chat history persistence — saves conversations as JSON in chat_history/.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

HISTORY_DIR = Path("chat_history")


@dataclass
class ChatRecord:
    id: str
    title: str
    model: str
    messages: list
    created_at: str
    updated_at: str


class ChatHistoryService:
    def __init__(self, history_dir: Path = HISTORY_DIR) -> None:
        self._dir = history_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        messages: list[dict],
        model: str = "",
        chat_id: str | None = None,
    ) -> ChatRecord:
        now = datetime.utcnow().isoformat()

        if chat_id:
            path = self._dir / f"{chat_id}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                data["messages"] = messages
                data["updated_at"] = now
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                return ChatRecord(**data)

        title = next(
            (m["content"][:60] for m in messages if m.get("role") == "user"),
            "새 대화",
        )
        record = ChatRecord(
            id=str(uuid.uuid4()),
            title=title,
            model=model,
            messages=messages,
            created_at=now,
            updated_at=now,
        )
        path = self._dir / f"{record.id}.json"
        path.write_text(
            json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return record

    def list_all(self) -> list[dict]:
        out: list[dict] = []
        for f in sorted(
            self._dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                out.append(
                    {
                        "id": data["id"],
                        "title": data["title"],
                        "model": data.get("model", ""),
                        "created_at": data["created_at"],
                        "updated_at": data["updated_at"],
                        "message_count": len(data.get("messages", [])),
                    }
                )
            except Exception:
                pass
        return out

    def get(self, chat_id: str) -> dict | None:
        path = self._dir / f"{chat_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def delete(self, chat_id: str) -> bool:
        path = self._dir / f"{chat_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False


chat_history_service = ChatHistoryService()
