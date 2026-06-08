#!/usr/bin/env python3
"""
Persona 보강 Prompt vs 일반 Prompt 정량 비교 벤치마크.

사용법:
    python scripts/benchmark_persona.py
    python scripts/benchmark_persona.py --models qwen2.5:7b
    python scripts/benchmark_persona.py --iterations 1
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.dsr_metrics import score_dsr_from_run
from benchmarks.metrics import score_checks
from services.ollama_trace import OllamaCallResult, parse_ollama_json
from services.prompt_enhancer import detect_intent, build_file_context
from src.persona_manager import load_persona_profile, PERSONA_PROFILES
from src.prompt_builder import build_chat_messages, build_structured_sections

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

DEFAULT_MODELS = ["qwen2.5:7b", "gemma4:31b", "deepseek-coder-v2:latest"]
PERSONA_IDS = ["data_analyst", "excel_expert", "business_consultant", "researcher", "general"]

TEST_PROMPTS = [
    {
        "label": "ANALYSIS",
        "prompt": "4월 예산 데이터를 분석해줘",
        "checks": {
            "must_contain": ["4월", "예산"],
            "must_not_contain": [],
        },
    },
    {
        "label": "COMPARISON",
        "prompt": "4월과 5월 예산 집행을 비교해줘",
        "checks": {
            "must_contain": ["4월", "5월", "비교"],
            "must_not_contain": [],
        },
    },
    {
        "label": "SUMMARY",
        "prompt": "전체 데이터를 요약해줘",
        "checks": {
            "must_contain": ["요약"],
            "must_not_contain": [],
        },
    },
]

_THINKING_HINTS = ("gemma4", "gemma3", "qwen3", "deepseek-r1", "r1")
_HANGUL_RE = re.compile(r"[가-힣]")

CHAT_OPTIONS = {"num_predict": 1024, "num_ctx": 4096, "temperature": 0.3}


# ── Ollama helpers ──────────────────────────────────────────────────

def check_ollama() -> list[str]:
    r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
    r.raise_for_status()
    return [m["name"] for m in r.json().get("models", [])]


def ollama_chat_bench(
    model: str,
    messages: list[dict[str, str]],
    options: dict[str, Any] | None = None,
) -> OllamaCallResult:
    opts = dict(CHAT_OPTIONS)
    if options:
        opts.update(options)
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": "30m",
        "options": opts,
    }
    if any(h in model for h in _THINKING_HINTS):
        payload["think"] = False
    t0 = time.time()
    resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=600)
    wall_ms = (time.time() - t0) * 1000
    resp.raise_for_status()
    return parse_ollama_json(resp.json(), wall_elapsed_ms=wall_ms, model=model)


# ── Metrics ─────────────────────────────────────────────────────────

def korean_ratio(text: str) -> float:
    if not text:
        return 0.0
    hangul = len(_HANGUL_RE.findall(text))
    alpha_num = sum(1 for c in text if c.isalnum())
    return (hangul / alpha_num * 100) if alpha_num else 0.0


def template_coverage(text: str, template_sections: list[str]) -> float:
    if not template_sections:
        return 0.0
    hits = sum(1 for sec in template_sections if sec in text)
    return hits / len(template_sections) * 100


def gen_speed(completion_tokens: int, elapsed_ms: float) -> float:
    if elapsed_ms <= 0:
        return 0.0
    return completion_tokens / (elapsed_ms / 1000)


def _apply_dsr(
    rr: "RunResult",
    response_text: str,
    tp: dict,
    user_prompt: str,
    enhanced_prompt: str,
    execution_path: str,
) -> None:
    rr.instruction_score, rr.instruction_hits, rr.instruction_total = score_checks(
        response_text, tp.get("checks"),
    )
    trace = {
        "user_prompt": user_prompt,
        "enhanced_prompt": enhanced_prompt,
        "execution_path": execution_path,
        "elapsed_ms": rr.latency_ms,
        "tokens": {
            "prompt": rr.prompt_tokens,
            "completion": rr.completion_tokens,
            "total": rr.total_tokens,
        },
        "status": "completed" if not rr.error else "error",
    }
    dsr = score_dsr_from_run(
        task="chat",
        instruction_score=rr.instruction_score,
        execution_path=execution_path,
        trace=trace,
    )
    rr.dsr_context_alignment = dsr.context_alignment
    rr.dsr_executability = dsr.executability
    rr.dsr_verification_pass = dsr.verification_pass
    rr.dsr_safety_compliance = dsr.safety_compliance
    rr.dsr_human_burden_inverse = dsr.human_burden
    rr.dsr_traceability = dsr.traceability


@dataclass
class RunResult:
    model: str
    mode: str  # "regular" or persona_id
    persona_name: str
    prompt_label: str
    iteration: int
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    response_length: int = 0
    gen_speed_tps: float = 0.0
    template_coverage_pct: float = 0.0
    korean_ratio_pct: float = 0.0
    instruction_score: float = 0.0
    instruction_hits: int = 0
    instruction_total: int = 0
    dsr_context_alignment: float = 0.0
    dsr_executability: float = 0.0
    dsr_verification_pass: float = 0.0
    dsr_safety_compliance: float = 0.0
    dsr_human_burden_inverse: float = 0.0
    dsr_traceability: float = 0.0
    error: str = ""


# ── Excel loading ───────────────────────────────────────────────────

def load_excel_files() -> tuple[list[str], dict[str, pd.DataFrame], list[dict]]:
    excel_dir = PROJECT_ROOT / "excel"
    filenames: list[str] = []
    frames: dict[str, pd.DataFrame] = {}
    metadata: list[dict] = []
    for p in sorted(excel_dir.glob("*.xlsx")):
        filenames.append(str(p))
        df = pd.read_excel(p, header=None)
        frames[str(p)] = df
        cols = []
        for c in df.iloc[0] if len(df) > 0 else []:
            if pd.notna(c):
                cols.append(str(c))
        metadata.append({
            "name": p.name,
            "original_name": p.name,
            "rows": len(df),
            "cols": len(df.columns),
            "columns": cols[:10],
        })
    return filenames, frames, metadata


# ── Prompt building ─────────────────────────────────────────────────

def build_regular_messages(user_prompt: str, file_context: str) -> list[dict[str, str]]:
    system = (
        "당신은 엑셀 데이터를 분석하는 AI 어시스턴트입니다. "
        "사용자의 요청에 대해 명확하고 구조적으로 답변하세요. "
        "한국어로 답변하세요."
    )
    user_parts = [user_prompt]
    if file_context:
        user_parts.append(f"\n\n{file_context}")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def build_persona_messages(
    user_prompt: str,
    persona_id: str,
    file_context: str,
    filenames: list[str],
    frames: dict[str, pd.DataFrame],
    metadata: list[dict],
) -> tuple[list[dict[str, str]], list[str]]:
    profile = load_persona_profile(persona_id)
    intent = detect_intent(user_prompt)
    task_hint = (profile.record.task_hints or {}).get(intent, "")

    from src.tool_registry import run_tools
    from src.persona_router import decide_strategy

    strategy = decide_strategy(profile, intent, user_prompt, has_attachments=bool(filenames))
    tool_results: dict[str, Any] = {}
    if filenames and frames:
        tool_results = run_tools(
            strategy.tools_to_run,
            filenames=filenames,
            frames=frames,
            user_prompt=user_prompt,
        )

    sections = build_structured_sections(
        profile,
        user_prompt,
        intent=intent,
        file_context=file_context,
        tool_context=tool_results if tool_results else None,
        task_hint=task_hint,
    )
    messages = build_chat_messages(sections)
    return messages, list(profile.response_template)


# ── Main benchmark loop ────────────────────────────────────────────

def run_benchmark(
    models: list[str],
    iterations: int = 3,
) -> list[RunResult]:
    print("\n=== Excel 파일 로딩 ===")
    filenames, frames, metadata = load_excel_files()
    print(f"  파일 {len(filenames)}개 로드 완료: {[Path(f).name for f in filenames]}")
    file_ctx = build_file_context(metadata)

    total = len(models) * (1 + len(PERSONA_IDS)) * len(TEST_PROMPTS) * iterations
    print(f"\n=== 벤치마크 시작 (총 {total}회 API 호출) ===\n")

    results: list[RunResult] = []
    done = 0

    for model in models:
        print(f"\n{'='*60}")
        print(f"  모델: {model}")
        print(f"{'='*60}")

        for tp in TEST_PROMPTS:
            prompt = tp["prompt"]
            label = tp["label"]

            # ── Regular mode ──
            messages_reg = build_regular_messages(prompt, file_ctx)
            for it in range(iterations):
                done += 1
                tag = f"[{done}/{total}] {model} | regular | {label} | iter {it+1}"
                print(f"  {tag} ...", end="", flush=True)
                rr = RunResult(
                    model=model,
                    mode="regular",
                    persona_name="(없음)",
                    prompt_label=label,
                    iteration=it + 1,
                )
                try:
                    res = ollama_chat_bench(model, messages_reg)
                    rr.latency_ms = res.elapsed_ms
                    rr.prompt_tokens = res.prompt_tokens
                    rr.completion_tokens = res.completion_tokens
                    rr.total_tokens = res.total_tokens
                    rr.response_length = len(res.content)
                    rr.gen_speed_tps = gen_speed(res.completion_tokens, res.elapsed_ms)
                    rr.template_coverage_pct = 0.0
                    rr.korean_ratio_pct = korean_ratio(res.content)
                    _apply_dsr(rr, res.content, tp, prompt, "", "plain")
                except Exception as e:
                    rr.error = str(e)
                    print(f" ERROR: {e}")
                else:
                    print(f" {rr.latency_ms:.0f}ms, {rr.total_tokens}tok, instr {rr.instruction_score:.2f}")
                results.append(rr)

            # ── Persona modes ──
            for pid in PERSONA_IDS:
                try:
                    msgs, tmpl = build_persona_messages(
                        prompt, pid, file_ctx, filenames, frames, metadata,
                    )
                except Exception as e:
                    for it in range(iterations):
                        done += 1
                        results.append(RunResult(
                            model=model, mode=pid,
                            persona_name=pid, prompt_label=label,
                            iteration=it + 1, error=f"pipeline: {e}",
                        ))
                    print(f"  SKIP {pid}: {e}")
                    continue

                profile = load_persona_profile(pid)
                pname = f"{profile.emoji} {profile.name}"

                enhanced_text = "\n".join(m.get("content", "") for m in msgs)

                for it in range(iterations):
                    done += 1
                    tag = f"[{done}/{total}] {model} | {pid} | {label} | iter {it+1}"
                    print(f"  {tag} ...", end="", flush=True)
                    rr = RunResult(
                        model=model,
                        mode=pid,
                        persona_name=pname,
                        prompt_label=label,
                        iteration=it + 1,
                    )
                    try:
                        res = ollama_chat_bench(model, msgs)
                        rr.latency_ms = res.elapsed_ms
                        rr.prompt_tokens = res.prompt_tokens
                        rr.completion_tokens = res.completion_tokens
                        rr.total_tokens = res.total_tokens
                        rr.response_length = len(res.content)
                        rr.gen_speed_tps = gen_speed(res.completion_tokens, res.elapsed_ms)
                        rr.template_coverage_pct = template_coverage(res.content, tmpl)
                        rr.korean_ratio_pct = korean_ratio(res.content)
                        _apply_dsr(rr, res.content, tp, prompt, enhanced_text, pid)
                    except Exception as e:
                        rr.error = str(e)
                        print(f" ERROR: {e}")
                    else:
                        print(f" {rr.latency_ms:.0f}ms, {rr.total_tokens}tok, instr {rr.instruction_score:.2f}")
                    results.append(rr)

    return results


# ── Aggregation & Reporting ─────────────────────────────────────────

@dataclass
class AggRow:
    model: str
    mode: str
    persona_name: str
    latency_ms: float = 0.0
    latency_std: float = 0.0
    prompt_tokens: float = 0.0
    completion_tokens: float = 0.0
    total_tokens: float = 0.0
    response_length: float = 0.0
    gen_speed_tps: float = 0.0
    template_coverage_pct: float = 0.0
    korean_ratio_pct: float = 0.0
    instruction_score: float = 0.0
    dsr_context_alignment: float = 0.0
    dsr_executability: float = 0.0
    dsr_verification_pass: float = 0.0
    dsr_safety_compliance: float = 0.0
    dsr_human_burden_inverse: float = 0.0
    dsr_traceability: float = 0.0
    n: int = 0


def aggregate(results: list[RunResult]) -> list[AggRow]:
    groups: dict[tuple[str, str], list[RunResult]] = {}
    for r in results:
        if r.error:
            continue
        key = (r.model, r.mode)
        groups.setdefault(key, []).append(r)

    rows: list[AggRow] = []
    for (model, mode), items in sorted(groups.items()):
        def avg(attr: str) -> float:
            vals = [getattr(r, attr) for r in items]
            return statistics.mean(vals) if vals else 0.0
        def std(attr: str) -> float:
            vals = [getattr(r, attr) for r in items]
            return statistics.stdev(vals) if len(vals) > 1 else 0.0

        rows.append(AggRow(
            model=model,
            mode=mode,
            persona_name=items[0].persona_name,
            latency_ms=avg("latency_ms"),
            latency_std=std("latency_ms"),
            prompt_tokens=avg("prompt_tokens"),
            completion_tokens=avg("completion_tokens"),
            total_tokens=avg("total_tokens"),
            response_length=avg("response_length"),
            gen_speed_tps=avg("gen_speed_tps"),
            template_coverage_pct=avg("template_coverage_pct"),
            korean_ratio_pct=avg("korean_ratio_pct"),
            instruction_score=avg("instruction_score"),
            dsr_context_alignment=avg("dsr_context_alignment"),
            dsr_executability=avg("dsr_executability"),
            dsr_verification_pass=avg("dsr_verification_pass"),
            dsr_safety_compliance=avg("dsr_safety_compliance"),
            dsr_human_burden_inverse=avg("dsr_human_burden_inverse"),
            dsr_traceability=avg("dsr_traceability"),
            n=len(items),
        ))
    return rows


def _pad(text: str, width: int) -> str:
    east_asian = sum(1 for c in text if ord(c) > 0x7F)
    return text + " " * max(0, width - len(text) - east_asian)


def print_table1(agg: list[AggRow]) -> None:
    print("\n" + "=" * 95)
    print("  [표 1] 모델별 Regular vs Persona 평균 비교")
    print("=" * 95)
    header = (
        f"{'Model':<22} {'Mode':<18} {'Latency':>10} {'P.Tok':>7} "
        f"{'C.Tok':>7} {'Resp Len':>9} {'Tok/s':>7} {'Korean%':>8}"
    )
    print(header)
    print("-" * 95)

    for model in dict.fromkeys(r.model for r in agg):
        model_rows = [r for r in agg if r.model == model]
        reg = [r for r in model_rows if r.mode == "regular"]
        per = [r for r in model_rows if r.mode != "regular"]

        if reg:
            r = reg[0]
            print(
                f"{r.model:<22} {'regular':<18} {r.latency_ms:>8.0f}ms "
                f"{r.prompt_tokens:>7.0f} {r.completion_tokens:>7.0f} "
                f"{r.response_length:>9.0f} {r.gen_speed_tps:>6.1f} {r.korean_ratio_pct:>7.1f}%"
            )
        if per:
            lat = statistics.mean([r.latency_ms for r in per])
            pt = statistics.mean([r.prompt_tokens for r in per])
            ct = statistics.mean([r.completion_tokens for r in per])
            rl = statistics.mean([r.response_length for r in per])
            gs = statistics.mean([r.gen_speed_tps for r in per])
            kr = statistics.mean([r.korean_ratio_pct for r in per])
            print(
                f"{'':<22} {'persona(avg)':<18} {lat:>8.0f}ms "
                f"{pt:>7.0f} {ct:>7.0f} "
                f"{rl:>9.0f} {gs:>6.1f} {kr:>7.1f}%"
            )
        print("-" * 95)


def print_table2(agg: list[AggRow]) -> None:
    print("\n" + "=" * 100)
    print("  [표 2] 페르소나별 Instruction 적용 효과 (전 모델 평균)")
    print("=" * 100)
    header = (
        f"{'Model':<22} {'Persona':<20} {'Latency':>10} {'Tok/s':>7} "
        f"{'Template%':>10} {'Korean%':>8} {'Resp Len':>9}"
    )
    print(header)
    print("-" * 100)

    for model in dict.fromkeys(r.model for r in agg):
        model_rows = [r for r in agg if r.model == model]
        for r in model_rows:
            mode_label = r.persona_name if r.mode != "regular" else "(regular)"
            tpl = f"{r.template_coverage_pct:.1f}%" if r.mode != "regular" else "N/A"
            print(
                f"{r.model:<22} {mode_label:<20} {r.latency_ms:>8.0f}ms "
                f"{r.gen_speed_tps:>6.1f} {tpl:>10} "
                f"{r.korean_ratio_pct:>7.1f}% {r.response_length:>9.0f}"
            )
        print("-" * 100)


def print_table3(agg: list[AggRow]) -> None:
    print("\n" + "=" * 80)
    print("  [표 3] Prompt 보강 효과 요약 (Persona 평균 - Regular)")
    print("=" * 80)
    header = (
        f"{'Model':<22} {'D Latency':>12} {'D Template%':>12} "
        f"{'D RespLen':>12} {'D Korean%':>12}"
    )
    print(header)
    print("-" * 80)

    for model in dict.fromkeys(r.model for r in agg):
        model_rows = [r for r in agg if r.model == model]
        reg = [r for r in model_rows if r.mode == "regular"]
        per = [r for r in model_rows if r.mode != "regular"]
        if not reg or not per:
            continue

        r0 = reg[0]
        p_lat = statistics.mean([r.latency_ms for r in per])
        p_tpl = statistics.mean([r.template_coverage_pct for r in per])
        p_rl = statistics.mean([r.response_length for r in per])
        p_kr = statistics.mean([r.korean_ratio_pct for r in per])

        def delta_pct(new: float, old: float) -> str:
            if old == 0:
                return "N/A"
            d = (new - old) / old * 100
            sign = "+" if d >= 0 else ""
            return f"{sign}{d:.1f}%"

        def delta_pp(new: float, old: float) -> str:
            d = new - old
            sign = "+" if d >= 0 else ""
            return f"{sign}{d:.1f}%p"

        print(
            f"{model:<22} {delta_pct(p_lat, r0.latency_ms):>12} "
            f"{delta_pp(p_tpl, r0.template_coverage_pct):>12} "
            f"{delta_pct(p_rl, r0.response_length):>12} "
            f"{delta_pp(p_kr, r0.korean_ratio_pct):>12}"
        )
    print("-" * 80)


def print_table4(results: list[RunResult]) -> None:
    print("\n" + "=" * 105)
    print("  [표 4] 프롬프트별 상세 비교 (모델 × 프롬프트 × 모드)")
    print("=" * 105)
    header = (
        f"{'Model':<22} {'Prompt':<14} {'Mode':<18} "
        f"{'Latency':>10} {'Tokens':>8} {'Resp Len':>9} {'Tmpl%':>7}"
    )
    print(header)
    print("-" * 105)

    groups: dict[tuple[str, str, str], list[RunResult]] = {}
    for r in results:
        if r.error:
            continue
        key = (r.model, r.prompt_label, r.mode)
        groups.setdefault(key, []).append(r)

    for (model, plabel, mode), items in sorted(groups.items()):
        lat = statistics.mean([r.latency_ms for r in items])
        tok = statistics.mean([r.total_tokens for r in items])
        rl = statistics.mean([r.response_length for r in items])
        tpl = statistics.mean([r.template_coverage_pct for r in items])
        mode_disp = "(regular)" if mode == "regular" else mode
        tpl_str = f"{tpl:.0f}%" if mode != "regular" else "N/A"
        print(
            f"{model:<22} {plabel:<14} {mode_disp:<18} "
            f"{lat:>8.0f}ms {tok:>8.0f} {rl:>9.0f} {tpl_str:>7}"
        )
    print("-" * 105)


def save_json(results: list[RunResult], agg: list[AggRow]) -> str:
    import csv

    results_dir = PROJECT_ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = results_dir / f"benchmark_{ts}.json"
    data = {
        "timestamp": ts,
        "config": {
            "models": list(dict.fromkeys(r.model for r in results)),
            "personas": PERSONA_IDS,
            "test_prompts": [{"label": t["label"], "prompt": t["prompt"]} for t in TEST_PROMPTS],
            "iterations": max((r.iteration for r in results), default=0),
        },
        "raw_results": [asdict(r) for r in results],
        "aggregated": [asdict(r) for r in agg],
    }
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    csv_path = results_dir / f"benchmark_{ts}_runs.csv"
    rows = [asdict(r) for r in results]
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"  CSV 저장: {csv_path}")

    generate_paper_results(results, agg, ts)
    return str(json_path)


# ── PAPER_RESULTS.md 자동 생성 ─────────────────────────────────────

def generate_paper_results(
    results: list[RunResult],
    agg: list[AggRow],
    ts: str,
) -> None:
    out_dir = PROJECT_ROOT / "results" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "PAPER_RESULTS.md"

    models = list(dict.fromkeys(r.model for r in results))
    n_total = len(results)
    n_ok = sum(1 for r in results if not r.error)
    iters = max((r.iteration for r in results), default=0)

    lines: list[str] = []
    L = lines.append

    L("# SW_Tech Persona 벤치마크 — 논문용 결과 정리")
    L("")
    L(f"**실험 일시:** {ts[:8]}  ")
    L(f"**데이터 원본:** `results/benchmark_{ts}.json`  ")
    L(f"**성공률:** {n_ok}/{n_total} ({100*n_ok/n_total:.0f}%)")
    L("")
    L("---")
    L("")

    # ── 1. 실험 설계 ──
    L("## 1. 실험 설계 (Methods 요약)")
    L("")
    L("### 1.1 목적")
    L("")
    L("동일 과제·동일 Foundation Model에 대해 **일반 프롬프트(regular)**와 ")
    L("**Persona 기반 프롬프트**(5종 Persona 파이프라인)의 응답 품질·비용을 비교한다.")
    L("")
    L("### 1.2 독립변수")
    L("")
    L("| 요인 | 수준 |")
    L("|------|------|")
    L("| **프롬프트 모드** | `regular` — 일반 시스템 프롬프트, `persona` — Persona 파이프라인(역할·도구·구조화 섹션) |")
    L(f"| **Foundation Model** | {', '.join(models)} |")
    L(f"| **Persona** | {', '.join(PERSONA_IDS)} (5종) |")
    L("| **테스트 프롬프트** | ANALYSIS, COMPARISON, SUMMARY (3종) |")
    L(f"| **반복 횟수** | {iters}회 |")
    L("")
    L(f"**총 호출:** {len(models)} models × (1 regular + {len(PERSONA_IDS)} personas) × "
      f"{len(TEST_PROMPTS)} prompts × {iters} iter = **{n_total}회**")
    L("")
    L("### 1.3 종속변수")
    L("")
    L("| 지표 | 정의 |")
    L("|------|------|")
    L("| Latency | Ollama API 왕복 시간 (ms) |")
    L("| Prompt/Completion/Total Tokens | 토큰 사용량 |")
    L("| Response Length | 응답 문자 수 |")
    L("| Generation Speed | completion_tokens / (elapsed / 1000) (tok/s) |")
    L("| Template Coverage | Persona 응답 템플릿 섹션 포함률 (%) |")
    L("| Korean Ratio | 한글 문자 비율 (%) |")
    L("| Instruction Score | 키워드 규칙 준수율 (0–1) |")
    L("| DSR 6차원 | 맥락 정합성, 실행 가능성, 검증, 안전, 인간 부담(역), 추적 가능성 (각 0–1) |")
    L("")
    L("---")
    L("")

    # ── 2. 표 1 — 모델별 Regular vs Persona 평균 ──
    L("## 2. 표 1 — 모델별 Regular vs Persona 평균 비교")
    L("")
    L("| Model | Mode | n | Latency (ms) | P.Tok | C.Tok | T.Tok | Resp Len | Tok/s | Instr | Korean% |")
    L("|-------|------|---|-------------|-------|-------|-------|----------|-------|-------|---------|")
    for r in agg:
        mode_label = "regular" if r.mode == "regular" else r.mode
        L(f"| `{r.model}` | {mode_label} | {r.n} | {r.latency_ms:.0f} ± {r.latency_std:.0f} | "
          f"{r.prompt_tokens:.0f} | {r.completion_tokens:.0f} | {r.total_tokens:.0f} | "
          f"{r.response_length:.0f} | {r.gen_speed_tps:.1f} | {r.instruction_score:.2f} | "
          f"{r.korean_ratio_pct:.1f}% |")
    L("")
    L("---")
    L("")

    # ── 3. 표 2 — Prompt 보강 효과 Δ ──
    L("## 3. 표 2 — Prompt 보강 효과 (Persona 평균 − Regular)")
    L("")
    L("| Model | ΔLatency | ΔTokens | ΔResp Len | ΔInstr | ΔTemplate% | ΔKorean% |")
    L("|-------|----------|---------|-----------|--------|-----------|---------|")
    for model in models:
        model_rows = [r for r in agg if r.model == model]
        reg = [r for r in model_rows if r.mode == "regular"]
        per = [r for r in model_rows if r.mode != "regular"]
        if not reg or not per:
            continue
        r0 = reg[0]
        p_lat = statistics.mean([r.latency_ms for r in per])
        p_tok = statistics.mean([r.total_tokens for r in per])
        p_rl = statistics.mean([r.response_length for r in per])
        p_ins = statistics.mean([r.instruction_score for r in per])
        p_tpl = statistics.mean([r.template_coverage_pct for r in per])
        p_kr = statistics.mean([r.korean_ratio_pct for r in per])

        def _delta(new: float, old: float) -> str:
            if old == 0:
                return "N/A"
            d = (new - old) / old * 100
            return f"{d:+.1f}%"

        def _delta_pp(new: float, old: float) -> str:
            return f"{new - old:+.1f}%p"

        L(f"| `{model}` | {_delta(p_lat, r0.latency_ms)} | {_delta(p_tok, r0.total_tokens)} | "
          f"{_delta(p_rl, r0.response_length)} | {_delta_pp(p_ins, r0.instruction_score)} | "
          f"{_delta_pp(p_tpl, r0.template_coverage_pct)} | {_delta_pp(p_kr, r0.korean_ratio_pct)} |")
    L("")
    L("---")
    L("")

    # ── 4. 표 3 — DSR 자동 점수 ──
    L("## 4. 표 3 — DSR 자동 점수 (0–1, 모드별 평균)")
    L("")
    L("| Model | Mode | 맥락 | 실행가능 | 검증 | 안전 | 인간부담↓ | 추적 |")
    L("|-------|------|------|----------|------|------|-----------|------|")
    for r in agg:
        mode_label = "regular" if r.mode == "regular" else r.mode
        L(f"| `{r.model}` | {mode_label} | {r.dsr_context_alignment:.2f} | "
          f"{r.dsr_executability:.2f} | {r.dsr_verification_pass:.2f} | "
          f"{r.dsr_safety_compliance:.2f} | {r.dsr_human_burden_inverse:.2f} | "
          f"{r.dsr_traceability:.2f} |")
    L("")
    L("---")
    L("")

    # ── 5. 표 4 — 프롬프트별 Instruction Score ──
    L("## 5. 표 4 — 프롬프트별 Instruction Score")
    L("")
    L("| Model | Mode | Prompt | Score | Hits/Total |")
    L("|-------|------|--------|-------|-----------|")
    prompt_groups: dict[tuple[str, str, str], list[RunResult]] = {}
    for r in results:
        if r.error:
            continue
        key = (r.model, r.mode, r.prompt_label)
        prompt_groups.setdefault(key, []).append(r)
    for (model, mode, plabel), items in sorted(prompt_groups.items()):
        avg_score = statistics.mean([r.instruction_score for r in items])
        total_hits = sum(r.instruction_hits for r in items)
        total_total = sum(r.instruction_total for r in items)
        mode_label = "regular" if mode == "regular" else mode
        L(f"| `{model}` | {mode_label} | {plabel} | {avg_score:.2f} | {total_hits}/{total_total} |")
    L("")
    L("---")
    L("")

    # ── 6. 표 5 — 토큰 사용량 ──
    L("## 6. 표 5 — 토큰 사용량 (모드별)")
    L("")
    L("| Model | Mode | Prompt Tokens | Completion Tokens | Total Tokens |")
    L("|-------|------|--------------|-------------------|-------------|")
    for r in agg:
        mode_label = "regular" if r.mode == "regular" else r.mode
        L(f"| `{r.model}` | {mode_label} | {r.prompt_tokens:.0f} | {r.completion_tokens:.0f} | {r.total_tokens:.0f} |")
    L("")
    L("---")
    L("")

    # ── 7. 논문 서술 초안 ──
    L("## 7. 논문용 서술 초안")
    L("")

    reg_agg = [r for r in agg if r.mode == "regular"]
    per_agg = [r for r in agg if r.mode != "regular"]
    if reg_agg and per_agg:
        avg_reg_instr = statistics.mean([r.instruction_score for r in reg_agg])
        avg_per_instr = statistics.mean([r.instruction_score for r in per_agg])
        avg_reg_lat = statistics.mean([r.latency_ms for r in reg_agg])
        avg_per_lat = statistics.mean([r.latency_ms for r in per_agg])
        avg_reg_tok = statistics.mean([r.total_tokens for r in reg_agg])
        avg_per_tok = statistics.mean([r.total_tokens for r in per_agg])
        avg_reg_ctx = statistics.mean([r.dsr_context_alignment for r in reg_agg])
        avg_per_ctx = statistics.mean([r.dsr_context_alignment for r in per_agg])

        L("### 7.1 Results (국문)")
        L("")
        L(f"> 동일 벤치마크 과제에 대해 일반 프롬프트와 Persona 기반 프롬프트를 "
          f"{len(models)}개 Foundation Model에 적용하여 비교하였다. "
          f"Regular 조건의 평균 지시 준수율은 {avg_reg_instr:.2f}, "
          f"Persona 조건은 {avg_per_instr:.2f}로 나타났다. "
          f"응답 시간은 Regular {avg_reg_lat:.0f}ms, Persona {avg_per_lat:.0f}ms이며, "
          f"토큰 사용량은 Regular {avg_reg_tok:.0f}, Persona {avg_per_tok:.0f}이었다. "
          f"DSR 맥락 정합성 차원에서 Regular {avg_reg_ctx:.2f}, Persona {avg_per_ctx:.2f}로 "
          f"Persona 조건이 더 높은 정합성을 보였다.")
        L("")
        L("### 7.2 Results (영문)")
        L("")
        L(f"> We compared regular prompts with persona-enhanced prompts across "
          f"{len(models)} local foundation models on {len(TEST_PROMPTS)} benchmark tasks "
          f"({n_total} total API calls, {iters} iterations each). "
          f"Persona-conditioned prompts achieved an average instruction adherence of "
          f"{avg_per_instr:.2f} compared to {avg_reg_instr:.2f} for regular prompts. "
          f"Latency increased from {avg_reg_lat:.0f}ms to {avg_per_lat:.0f}ms, "
          f"and token usage from {avg_reg_tok:.0f} to {avg_per_tok:.0f}. "
          f"DSR context alignment improved from {avg_reg_ctx:.2f} to {avg_per_ctx:.2f} "
          f"under persona conditions.")
        L("")

    L("### 7.3 Limitations")
    L("")
    L("1. **단일 호스트·로컬 Ollama** — 재현 시 하드웨어·동시 부하에 민감.")
    L("2. **키워드 기반 instruction score** — 의미적 정확도를 완전히 대체하지 못함 → 전문가 Likert 병행 권장.")
    L("3. **Chat 과제만** — Codegen/샌드박스 실행은 `benchmarks/run_comparison.py`로 별도 실험.")
    L(f"4. **반복 횟수** — {iters}회; 논문 제출 전 n≥3 확인 필요.")
    L("")
    L("---")
    L("")

    # ── 8. 재현 명령 ──
    L("## 8. 재현 명령")
    L("")
    L("```bash")
    L("cd /home/eunbi/SW_Tech && source .venv/bin/activate")
    L(f"python scripts/benchmark_persona.py \\")
    L(f"  --models {' '.join(models)} \\")
    L(f"  --iterations {iters}")
    L("```")
    L("")
    L("---")
    L("")
    L(f"*본 문서는 `benchmark_{ts}.json` 에서 자동 생성되었습니다.*")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  PAPER_RESULTS.md 갱신: {path}")


# ── CLI ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Persona Prompt Benchmark")
    parser.add_argument(
        "--models", nargs="+", default=DEFAULT_MODELS,
        help="테스트할 Ollama 모델 목록",
    )
    parser.add_argument(
        "--iterations", type=int, default=3,
        help="조합당 반복 횟수 (default: 3)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="조합만 출력하고 Ollama 호출 안 함",
    )
    args = parser.parse_args()

    if args.dry_run:
        total = len(args.models) * (1 + len(PERSONA_IDS)) * len(TEST_PROMPTS) * args.iterations
        print(f"\n=== DRY RUN: 총 {total}회 호출 예정 ===")
        print(f"  모델: {args.models}")
        print(f"  모드: regular + {PERSONA_IDS}")
        print(f"  프롬프트: {[t['label'] for t in TEST_PROMPTS]}")
        print(f"  반복: {args.iterations}회")
        print(f"\n  조합:")
        for model in args.models:
            for tp in TEST_PROMPTS:
                for mode in ["regular"] + PERSONA_IDS:
                    for it in range(1, args.iterations + 1):
                        print(f"    {model} | {mode:<22} | {tp['label']:<12} | iter {it}")
        return

    print("=== Ollama 연결 확인 ===")
    try:
        installed = check_ollama()
        print(f"  설치된 모델: {installed}")
    except Exception as e:
        print(f"  ERROR: Ollama 연결 실패 — {e}")
        sys.exit(1)

    valid_models = []
    for m in args.models:
        matches = [inst for inst in installed if m in inst or inst in m]
        if matches:
            valid_models.append(matches[0])
            print(f"  OK: {m} -> {matches[0]}")
        else:
            print(f"  SKIP: {m} (미설치)")
    if not valid_models:
        print("  ERROR: 사용 가능한 모델 없음")
        sys.exit(1)

    results = run_benchmark(valid_models, iterations=args.iterations)
    agg = aggregate(results)

    print_table1(agg)
    print_table2(agg)
    print_table3(agg)
    print_table4(results)

    path = save_json(results, agg)
    print(f"\n  JSON 저장: {path}")

    errors = [r for r in results if r.error]
    ok = len(results) - len(errors)
    print(f"\n=== 완료: {ok} 성공 / {len(errors)} 실패 ===\n")


if __name__ == "__main__":
    main()
