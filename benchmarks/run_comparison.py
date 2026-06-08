#!/usr/bin/env python3
"""
SW_Tech 정량 벤치마크 — 일반 Prompt vs Persona 보강 × 모델별 비교.

사용 예:
  cd /home/eunbi/SW_Tech
  source .venv/bin/activate
  python benchmarks/run_comparison.py --models qwen2.5:7b,gemma3:4b --quick

결과: results/benchmarks/<timestamp>/runs.csv, summary.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

_BENCH_DIR = Path(__file__).resolve().parent
_ROOT = _BENCH_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from benchmarks._app_loader import load_app
from benchmarks.dsr_metrics import score_dsr_from_run
from benchmarks.metrics import RunRecord, score_checks, write_outputs
from src.persona_pipeline import prepare_persona_execution
from src.prompt_builder import sections_to_preview_text

MODES = ("plain", "persona_struct", "persona_enh")


def _attach_dsr(
    rec: RunRecord,
    *,
    case: dict[str, Any],
    code: str = "",
    enhanced: str = "",
    frame_columns: list[str] | None = None,
    hitl_confirm: bool = False,
    llm_retries: int = 0,
) -> None:
    trace = {
        "user_prompt": case.get("prompt"),
        "enhanced_prompt": enhanced,
        "execution_path": rec.execution_path,
        "generated_code": code,
        "elapsed_ms": rec.elapsed_ms,
        "tokens": {
            "prompt": rec.prompt_tokens,
            "completion": rec.completion_tokens,
            "total": rec.total_tokens,
        },
        "status": "completed" if rec.ok else "error",
    }
    dsr = score_dsr_from_run(
        task=rec.task,
        code=code,
        sandbox_ok=rec.sandbox_ok,
        instruction_score=rec.instruction_score,
        execution_path=rec.execution_path,
        trace=trace,
        frame_columns=frame_columns,
        hitl_confirm=hitl_confirm,
        llm_retries=llm_retries,
    )
    rec.extra.update(dsr.as_dict())
    if dsr.notes:
        rec.extra["dsr_notes"] = "; ".join(dsr.notes)


def _ollama_tags(base_url: str) -> list[str]:
    r = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=10)
    r.raise_for_status()
    return [m["name"] for m in r.json().get("models", [])]


def _frames_from_spec(spec: dict[str, Any]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for name, body in spec.items():
        cols = body.get("columns") or {}
        out[name] = pd.DataFrame(cols)
    return out


def _build_prompts(
    case: dict[str, Any],
    mode: str,
    persona_id: str,
    frames: dict[str, pd.DataFrame] | None,
    rewrite_model: str,
) -> tuple[str, list[dict], str, str, str]:
    """messages, system_prompt, user_for_codegen, enhanced_preview, execution_path."""
    user = case["prompt"]
    if mode == "plain":
        return (
            [{"role": "user", "content": user}],
            "",
            user,
            "",
            "plain",
        )

    plan = prepare_persona_execution(
        user,
        persona_id,
        filenames=list((frames or {}).keys()) or ["sample.xlsx"],
        frames=frames or {},
        files_metadata=[
            {"name": k, "rows": len(v), "cols": len(v.columns)}
            for k, v in (frames or {"df_0": pd.DataFrame({"a": [1]})}).items()
        ],
        use_enhancement=(mode == "persona_enh"),
        rewrite_model=rewrite_model if mode == "persona_enh" else "",
        use_rewrite=bool(rewrite_model) and mode == "persona_enh",
    )
    enhanced = plan.preview_text or sections_to_preview_text(plan.sections)
    system = plan.profile.record.system_prompt

    if mode == "persona_struct":
        return (
            [{"role": "system", "content": system}, {"role": "user", "content": enhanced}],
            system,
            enhanced,
            enhanced,
            plan.execution_path,
        )

    return (
        [{"role": "system", "content": system}, {"role": "user", "content": enhanced}],
        system,
        enhanced,
        enhanced,
        plan.execution_path,
    )


def run_chat(
    app,
    *,
    case: dict[str, Any],
    model: str,
    mode: str,
    persona_id: str,
    rewrite_model: str,
) -> RunRecord:
    rec = RunRecord(
        case_id=case["id"],
        task="chat",
        model=model,
        mode=mode,
        persona_id=persona_id,
        ok=False,
    )
    try:
        messages, _sys, enhanced, _cg, path = _build_prompts(
            case, mode, persona_id, None, rewrite_model,
        )
        rec.execution_path = path
        rec.prompt_chars = len(case["prompt"])
        rec.enhanced_chars = len(enhanced) if enhanced else rec.prompt_chars
        if rec.prompt_chars:
            rec.enhancement_ratio = rec.enhanced_chars / rec.prompt_chars

        result = app.ollama_chat(model, messages, temperature=0.3)
        text = (result.content or "") + (result.thinking or "")
        rec.response_chars = len(text)
        rec.elapsed_ms = float(result.elapsed_ms)
        rec.prompt_tokens = int(result.prompt_tokens)
        rec.completion_tokens = int(result.completion_tokens)
        rec.total_tokens = int(result.total_tokens)
        rec.instruction_score, rec.instruction_hits, rec.instruction_total = score_checks(
            text, case.get("checks"),
        )
        rec.ok = bool(result.content.strip()) or bool(result.thinking.strip())
        if not rec.ok:
            rec.error = "empty_response"
        _attach_dsr(rec, case=case, enhanced=enhanced)
    except Exception as exc:
        rec.error = str(exc)[:500]
    return rec


def run_codegen(
    app,
    *,
    case: dict[str, Any],
    model: str,
    mode: str,
    persona_id: str,
    rewrite_model: str,
) -> RunRecord:
    rec = RunRecord(
        case_id=case["id"],
        task="codegen",
        model=model,
        mode=mode,
        persona_id=persona_id,
        ok=False,
    )
    frames = _frames_from_spec(case.get("frames") or {})
    frame_names = list(frames.keys())
    try:
        messages, _sys, user_prompt, enhanced, path = _build_prompts(
            case, mode, persona_id, frames, rewrite_model,
        )
        rec.execution_path = path
        rec.prompt_chars = len(case["prompt"])
        rec.enhanced_chars = len(enhanced) if enhanced else rec.prompt_chars
        if rec.prompt_chars:
            rec.enhancement_ratio = rec.enhanced_chars / rec.prompt_chars

        if path == "tool_response":
            rec.ok = True
            rec.extra["skipped_llm"] = True
            _attach_dsr(rec, case=case, enhanced=enhanced, frame_columns=[])
            return rec

        data_context = _synthetic_data_context(frames)
        if mode == "plain":
            code_prompt = app.generate_code_prompt(
                case["prompt"],
                data_context,
                frame_names,
                frames=frames,
            )
        else:
            from src.prompt_builder import build_code_generation_prompt
            from src.persona_manager import load_persona_profile
            from services.prompt_enhancer import detect_intent

            profile = load_persona_profile(persona_id)
            code_prompt = build_code_generation_prompt(
                profile,
                case["prompt"],
                data_context,
                intent=detect_intent(case["prompt"]),
                tool_context={},
                flags=app._excel_codegen_flags(case["prompt"]),
            )

        gen = app.ollama_generate(model, code_prompt, temperature=0.1)
        code = app.extract_code_block(gen.content, fallback=gen.thinking)
        rec.code_extracted = bool(code)
        rec.code_lines = len(code.splitlines()) if code else 0
        rec.elapsed_ms = float(gen.elapsed_ms)
        rec.prompt_tokens = int(gen.prompt_tokens)
        rec.completion_tokens = int(gen.completion_tokens)
        rec.total_tokens = int(gen.total_tokens)
        rec.response_chars = len(gen.content or "")

        check_text = code or gen.content or ""
        rec.instruction_score, rec.instruction_hits, rec.instruction_total = score_checks(
            check_text, case.get("checks"),
        )

        if not code:
            rec.error = "no_code_extracted"
            cols = [str(c) for df in frames.values() for c in df.columns]
            _attach_dsr(
                rec, case=case, code="", enhanced=enhanced,
                frame_columns=cols, hitl_confirm=True,
            )
            return rec

        exec_out = app.execute_pandas_code(code, frames)
        cols = [str(c) for df in frames.values() for c in df.columns]
        if "error" in exec_out:
            rec.error = exec_out["error"][:300]
            _attach_dsr(
                rec, case=case, code=code, enhanced=enhanced,
                frame_columns=cols, hitl_confirm=True,
            )
            return rec

        rec.sandbox_ok = True
        rec.ok = True
        if exec_out.get("dataframe") is not None:
            rec.result_rows = len(exec_out["dataframe"])
        _attach_dsr(
            rec, case=case, code=code, enhanced=enhanced,
            frame_columns=cols, hitl_confirm=True,
        )
    except Exception as exc:
        rec.error = str(exc)[:500]
    return rec


def _synthetic_data_context(frames: dict[str, pd.DataFrame]) -> str:
    parts: list[str] = []
    for name, df in frames.items():
        parts.append(f"### {name} ({len(df)} rows × {len(df.columns)} cols)")
        parts.append(f"Columns (repr): {[repr(c) for c in df.columns]}")
        parts.append(df.head(3).to_string())
    return "\n\n".join(parts)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SW_Tech prompt/persona/model benchmark")
    p.add_argument(
        "--models",
        default="qwen2.5:7b",
        help="쉼표 구분 Ollama 모델명",
    )
    p.add_argument(
        "--modes",
        default="plain,persona_enh",
        help=f"쉼표 구분: {','.join(MODES)}",
    )
    p.add_argument(
        "--personas",
        default="general,excel_expert,business_consultant",
        help="persona_enh/struct 시 사용할 persona id",
    )
    p.add_argument(
        "--tasks",
        default="chat,codegen",
        help="chat,codegen",
    )
    p.add_argument(
        "--cases",
        type=Path,
        default=_BENCH_DIR / "cases.json",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=_ROOT / "results" / "benchmarks",
    )
    p.add_argument(
        "--rewrite-model",
        default="",
        help="persona_enh 시 prompt_rewriter 모델 (비우면 리라이트 생략)",
    )
    p.add_argument(
        "--quick",
        action="store_true",
        help="chat 1건 + codegen 1건, 모델 1개, plain+persona_enh 만",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="조합만 출력하고 Ollama 호출 안 함",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    personas = [p.strip() for p in args.personas.split(",") if p.strip()]
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]

    if args.quick:
        models = models[:1]
        modes = [m for m in ("plain", "persona_enh") if m in modes or not args.modes]
        if not modes:
            modes = ["plain", "persona_enh"]
        personas = personas[:1]
        cases["chat_cases"] = (cases.get("chat_cases") or [])[:1]
        cases["codegen_cases"] = (cases.get("codegen_cases") or [])[:1]

    combos: list[tuple[str, str, str, str, dict]] = []
    for task in tasks:
        case_list = cases.get(f"{task}_cases") or []
        for case in case_list:
            pid = case.get("persona_id") or personas[0]
            for model in models:
                for mode in modes:
                    if mode == "plain":
                        combos.append((task, case, model, mode, pid))
                    elif pid in personas or pid == case.get("persona_id"):
                        combos.append((task, case, model, mode, pid))

    print(f"총 {len(combos)}회 실행 예정 → {args.output}/<timestamp>")
    if args.dry_run:
        for c in combos:
            print(f"  {c[0]} | {c[2]} | {c[3]} | {c[1]['id']}")
        return 0

    app = load_app()
    base_url = app.OLLAMA_URL
    available = set(_ollama_tags(base_url))
    missing = [m for m in models if m not in available]
    if missing:
        print(f"⚠️ 설치되지 않은 모델: {missing}")
        print(f"   사용 가능: {sorted(available)}")
        models = [m for m in models if m in available]
    if not models:
        print("실행할 모델이 없습니다. ollama pull 후 다시 시도하세요.")
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = args.output / ts
    records: list[RunRecord] = []

    # 기본: 리라이트 OFF (persona_enh = 구조화 섹션·도구만). 리라이트 실험 시 --rewrite-model qwen2.5:7b
    rewrite_model = args.rewrite_model.strip() if args.rewrite_model else ""
    for i, (task, case, model, mode, persona_id) in enumerate(combos, 1):
        label = f"[{i}/{len(combos)}] {task} {case['id']} | {model} | {mode}"
        print(label, flush=True)
        t0 = time.perf_counter()
        if task == "chat":
            rec = run_chat(
                app,
                case=case,
                model=model,
                mode=mode,
                persona_id=persona_id,
                rewrite_model=rewrite_model,
            )
        else:
            rec = run_codegen(
                app,
                case=case,
                model=model,
                mode=mode,
                persona_id=persona_id,
                rewrite_model=rewrite_model,
            )
        wall = (time.perf_counter() - t0) * 1000
        rec.extra["wall_ms"] = wall
        status = "OK" if rec.ok else f"FAIL ({rec.error})"
        print(
            f"    → {status} | {rec.elapsed_ms:.0f}ms | tok {rec.total_tokens} | "
            f"instr {rec.instruction_score:.2f}",
            flush=True,
        )
        records.append(rec)

    write_outputs(records, out_dir)
    print(f"\n저장 완료:\n  {out_dir / 'runs.csv'}\n  {out_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
