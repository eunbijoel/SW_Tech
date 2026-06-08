"""벤치마크 지표 계산·집계."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunRecord:
    case_id: str
    task: str
    model: str
    mode: str
    persona_id: str
    ok: bool
    error: str = ""
    elapsed_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_chars: int = 0
    enhanced_chars: int = 0
    enhancement_ratio: float = 0.0
    execution_path: str = ""
    code_extracted: bool = False
    code_lines: int = 0
    sandbox_ok: bool = False
    result_rows: int = 0
    instruction_score: float = 0.0
    instruction_hits: int = 0
    instruction_total: int = 0
    response_chars: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def score_checks(text: str, checks: dict[str, Any] | None) -> tuple[float, int, int]:
    """규칙 기반 instruction 준수 점수 (0~1)."""
    if not checks:
        return 1.0, 0, 0
    rules: list[tuple[str, str, bool]] = []
    for pat in checks.get("must_contain") or []:
        rules.append((pat, "must_contain", True))
    for pat in checks.get("must_not_contain") or []:
        rules.append((pat, "must_not_contain", False))
    if not rules:
        return 1.0, 0, 0
    hits = 0
    lower = text.lower()
    for pat, _kind, positive in rules:
        found = pat.lower() in lower if pat.isascii() else pat in text
        if positive and found:
            hits += 1
        elif not positive and not found:
            hits += 1
    return hits / len(rules), hits, len(rules)


def records_to_csv_rows(records: list[RunRecord]) -> list[dict[str, Any]]:
    return [asdict(r) for r in records]


def write_outputs(records: list[RunRecord], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = records_to_csv_rows(records)
    (out_dir / "runs.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if rows:
        import csv

        flat_rows: list[dict[str, Any]] = []
        for row in rows:
            extra = dict(row.get("extra") or {})
            flat = {k: v for k, v in row.items() if k != "extra"}
            for k, v in extra.items():
                if k.startswith("dsr_"):
                    flat[k] = v
            flat["extra_json"] = json.dumps(extra, ensure_ascii=False)
            flat_rows.append(flat)

        fieldnames = list(flat_rows[0].keys())
        with (out_dir / "runs.csv").open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flat_rows)
    (out_dir / "summary.md").write_text(summarize_markdown(records), encoding="utf-8")


def summarize_markdown(records: list[RunRecord]) -> str:
    if not records:
        return "# Benchmark\n\n(결과 없음)\n"

    from collections import defaultdict

    groups: dict[tuple[str, str, str], list[RunRecord]] = defaultdict(list)
    for r in records:
        groups[(r.task, r.model, r.mode)].append(r)

    lines = [
        "# SW_Tech 벤치마크 요약",
        "",
        "| task | model | mode | n | ok% | avg_ms | avg_tokens | instr_score | sandbox_ok% |",
        "|------|-------|------|---|-----|--------|------------|-------------|-------------|",
    ]
    for (task, model, mode), items in sorted(groups.items()):
        n = len(items)
        ok_pct = 100 * sum(1 for x in items if x.ok) / n
        avg_ms = sum(x.elapsed_ms for x in items) / n
        avg_tok = sum(x.total_tokens for x in items) / n
        avg_instr = sum(x.instruction_score for x in items) / n
        sb = [x for x in items if x.task == "codegen"]
        sb_pct = (
            100 * sum(1 for x in sb if x.sandbox_ok) / len(sb) if sb else 0.0
        )
        lines.append(
            f"| {task} | `{model}` | {mode} | {n} | {ok_pct:.0f}% | "
            f"{avg_ms:.0f} | {avg_tok:.0f} | {avg_instr:.2f} | {sb_pct:.0f}% |"
        )

    lines.extend(["", "## Persona 보강 효과 (동일 model·case)", ""])
    by_case_model: dict[tuple[str, str], dict[str, RunRecord]] = defaultdict(dict)
    for r in records:
        by_case_model[(r.case_id, r.model)][r.mode] = r

    lines.append(
        "| case | model | plain_ms | persona_ms | Δms | plain_tok | persona_tok | "
        "plain_instr | persona_instr |",
    )
    lines.append("|------|-------|----------|------------|-----|-----------|-------------|-------------|---------------|")
    for (case_id, model), modes in sorted(by_case_model.items()):
        plain = modes.get("plain")
        persona = modes.get("persona_enh") or modes.get("persona_struct")
        if not plain or not persona:
            continue
        d_ms = persona.elapsed_ms - plain.elapsed_ms
        lines.append(
            f"| {case_id} | `{model}` | {plain.elapsed_ms:.0f} | {persona.elapsed_ms:.0f} | "
            f"{d_ms:+.0f} | {plain.total_tokens} | {persona.total_tokens} | "
            f"{plain.instruction_score:.2f} | {persona.instruction_score:.2f} |",
        )

    lines.extend(["", "## DSR 자동 지표 (평균)", ""])
    lines.append(
        "| task | model | mode | context | executability | verification | "
        "safety | human_burden↓ | traceability |",
    )
    lines.append(
        "|------|-------|------|---------|---------------|--------------|"
        "------|---------------|--------------|",
    )

    def _avg(items: list[RunRecord], key: str) -> float:
        vals = [float((x.extra or {}).get(key, 0)) for x in items]
        return sum(vals) / len(vals) if vals else 0.0

    for (task, model, mode), items in sorted(groups.items()):
        lines.append(
            f"| {task} | `{model}` | {mode} | "
            f"{_avg(items, 'dsr_context_alignment'):.2f} | "
            f"{_avg(items, 'dsr_executability'):.2f} | "
            f"{_avg(items, 'dsr_verification_pass'):.2f} | "
            f"{_avg(items, 'dsr_safety_compliance'):.2f} | "
            f"{_avg(items, 'dsr_human_burden_inverse'):.2f} | "
            f"{_avg(items, 'dsr_traceability'):.2f} |",
        )
    return "\n".join(lines) + "\n"
