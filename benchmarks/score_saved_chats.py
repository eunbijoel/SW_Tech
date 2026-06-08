#!/usr/bin/env python3
"""저장된 results/chat_*.md trace 로 DSR 추적성·안전성 집계."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from benchmarks.dsr_metrics import score_trace_from_md_body
from services.conversation_store import markdown_to_messages


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("paths", nargs="+", help="chat_*.md 경로")
    p.add_argument("-o", type=Path, default=_ROOT / "results" / "benchmarks" / "saved_chat_scores.csv")
    args = p.parse_args()

    rows: list[dict] = []
    for pat in args.paths:
        p = Path(pat)
        paths = sorted(p.parent.glob(p.name)) if "*" in pat else [p]
        for path in paths:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for i, msg in enumerate(markdown_to_messages(text)):
                if msg.get("role") != "assistant":
                    continue
                trace = msg.get("trace") or {}
                dsr = score_trace_from_md_body("", trace)
                rows.append({
                    "file": path.name,
                    "turn": i,
                    "status": trace.get("status", ""),
                    "code_source": trace.get("code_source", ""),
                    **dsr.as_dict(),
                })

    if not rows:
        print("대상 없음")
        return 1

    args.o.parent.mkdir(parents=True, exist_ok=True)
    with args.o.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"저장: {args.o} ({len(rows)} assistant turns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
