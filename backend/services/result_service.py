"""
Result saving service.
Persists AI responses as markdown files and processed DataFrames as Excel.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backend.core.config import settings
from backend.core.logging import get_logger

log = get_logger(__name__)

MD_DIR   = settings.RESULTS_DIR / "markdown"
XLSX_DIR = settings.RESULTS_DIR / "excel"


class ResultService:
    def save_markdown(
        self,
        prompt: str,
        response: str,
        model: str = "",
        title: str = "",
    ) -> Path:
        """Save a prompt+response pair as a formatted markdown file."""
        ts = datetime.now(timezone.utc)
        result_id = str(uuid.uuid4())[:8]
        filename = f"{ts.strftime('%Y%m%d_%H%M%S')}_{result_id}.md"
        path = MD_DIR / filename

        header = title or prompt[:60].replace("\n", " ")
        content = (
            f"# {header}\n\n"
            f"**Date:** {ts.isoformat()}\n"
            f"**Model:** {model or 'unknown'}\n\n"
            f"---\n\n"
            f"## Prompt\n\n{prompt}\n\n"
            f"## Response\n\n{response}\n"
        )
        path.write_text(content, encoding="utf-8")
        log.info("Saved markdown result", path=str(path))
        return path

    def save_excel(
        self,
        df: pd.DataFrame,
        label: str = "",
    ) -> Path:
        """Save a DataFrame as an Excel file in the results directory."""
        ts = datetime.now(timezone.utc)
        result_id = str(uuid.uuid4())[:8]
        safe_label = "".join(c if c.isalnum() else "_" for c in label)[:30]
        filename = f"{ts.strftime('%Y%m%d_%H%M%S')}_{safe_label or result_id}.xlsx"
        path = XLSX_DIR / filename

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Result")

        log.info("Saved Excel result", path=str(path), rows=len(df))
        return path

    def list_results(self, result_type: str = "all") -> dict[str, list[dict]]:
        """
        List saved results.
        result_type: "markdown" | "excel" | "all"
        """
        out: dict[str, list[dict]] = {"markdown": [], "excel": []}

        if result_type in ("markdown", "all"):
            for p in sorted(MD_DIR.glob("*.md"), reverse=True):
                out["markdown"].append({
                    "filename": p.name,
                    "path": str(p),
                    "size_kb": round(p.stat().st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(
                        p.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                })

        if result_type in ("excel", "all"):
            for p in sorted(XLSX_DIR.glob("*.xlsx"), reverse=True):
                out["excel"].append({
                    "filename": p.name,
                    "path": str(p),
                    "size_kb": round(p.stat().st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(
                        p.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                })

        return out

    def read_markdown(self, filename: str) -> str | None:
        path = MD_DIR / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def delete_result(self, result_type: str, filename: str) -> bool:
        base = MD_DIR if result_type == "markdown" else XLSX_DIR
        path = base / filename
        if path.exists():
            path.unlink()
            log.info("Deleted result", path=str(path))
            return True
        return False


result_service = ResultService()
