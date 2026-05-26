"""
Step Flow 순차 실행 엔진 — 저장된 대화를 Step 단위로 연결·재실행.

흐름:
  Step 1 대화 → 핵심 내용 추출 → Step 2에 컨텍스트 주입 → 실행 → Step 3에 전달
  각 Step에서 사용된 파일·컬럼·연산을 추적하여 데이터 흐름 기록.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services.conversation_store import markdown_to_messages


# ── 데이터 흐름 추적 ─────────────────────────────────────────────

@dataclass
class DataFlowRecord:
    """한 Step에서 발생한 데이터 흐름 기록."""
    files_used: list[str] = field(default_factory=list)
    columns_referenced: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    output_shape: str = ""
    output_columns: list[str] = field(default_factory=list)


# ── Step 컨텍스트 ────────────────────────────────────────────────

@dataclass
class StepContext:
    """한 Step의 핵심 내용을 담는 컨텍스트."""
    step_id: str
    step_label: str
    user_prompt: str = ""
    detected_intent: str = ""
    generated_code: str = ""
    result_summary: str = ""
    data_flow: DataFlowRecord = field(default_factory=DataFlowRecord)
    raw_messages: list[dict] = field(default_factory=list)
    error: str = ""

    def is_valid(self) -> bool:
        return bool(self.user_prompt) and not self.error


@dataclass
class FlowExecutionResult:
    """전체 Flow 실행 결과."""
    flow_id: str
    steps: list[StepContext] = field(default_factory=list)
    data_flow_summary: str = ""
    status: str = "pending"


# ── 코드에서 데이터 흐름 추출 ─────────────────────────────────────

# pandas 연산 키워드 → 사용자 친화적 설명
_OP_PATTERNS: list[tuple[str, str]] = [
    (r"pd\.concat", "파일 통합 (concat)"),
    (r"\.merge\(", "데이터 병합 (merge)"),
    (r"\.groupby\(", "그룹별 집계 (groupby)"),
    (r"\.sort_values\(", "정렬 (sort)"),
    (r"\.filter\(|\.query\(", "필터링"),
    (r"\.pivot_table\(|\.pivot\(", "피벗 테이블"),
    (r"pd\.to_numeric", "숫자 변환"),
    (r"\.dropna\(", "결측값 제거"),
    (r"\.fillna\(", "결측값 채우기"),
    (r"\.drop_duplicates\(", "중복 제거"),
    (r"\.agg\(", "집계 연산"),
    (r"plt\.", "시각화 (차트)"),
    (r"\.describe\(", "기술 통계"),
    (r"집행률|집행 계", "집행률 계산"),
]

_COL_RE = re.compile(
    r"""(?:\[['"](.+?)['"]\])"""
    r"""|(?:\.(?:rename|agg|groupby)\(.*?['"](.+?)['"])""",
)


def _extract_operations_from_code(code: str) -> list[str]:
    """생성된 pandas 코드에서 수행된 연산 목록을 추출합니다."""
    ops = []
    for pattern, label in _OP_PATTERNS:
        if re.search(pattern, code):
            ops.append(label)
    return list(dict.fromkeys(ops))


def _extract_columns_from_code(code: str) -> list[str]:
    """코드에서 참조된 컬럼명을 추출합니다."""
    cols = set()
    for m in _COL_RE.finditer(code):
        col = m.group(1) or m.group(2)
        if col and not col.startswith("df_") and len(col) < 30:
            cols.add(col)
    return sorted(cols)


def _extract_files_from_code(code: str) -> list[str]:
    """코드에서 참조된 DataFrame 변수(df_0, df_1 등)를 추출합니다."""
    return sorted(set(re.findall(r"df_\d+", code)))


def _extract_result_shape(assistant_content: str) -> str:
    """AI 응답에서 결과 shape 정보를 추출합니다."""
    m = re.search(r"(\d+)행\s*[×x]\s*(\d+)열", assistant_content)
    if m:
        return f"{m.group(1)}행 × {m.group(2)}열"
    m = re.search(r"(\d+행\s*×\s*\d+열)", assistant_content)
    if m:
        return m.group(1)
    return ""


# ── Step 컨텍스트 추출 ───────────────────────────────────────────

def extract_step_context(
    step_id: str,
    step_label: str,
    chat_filename: str,
    *,
    results_dir: Path | None = None,
) -> StepContext:
    """저장된 대화 파일에서 Step 컨텍스트를 추출합니다.

    대화의 첫 번째 사용자 메시지 = 핵심 요청,
    첫 번째 AI 응답 = 핵심 결과로 취급합니다.
    """
    root = results_dir or Path("./results")
    path = root / chat_filename
    if not path.exists():
        return StepContext(
            step_id=step_id,
            step_label=step_label,
            error=f"대화 파일을 찾을 수 없습니다: {chat_filename}",
        )

    try:
        messages = markdown_to_messages(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return StepContext(
            step_id=step_id,
            step_label=step_label,
            error=f"대화 파일 파싱 실패: {exc}",
        )

    if not messages:
        return StepContext(
            step_id=step_id,
            step_label=step_label,
            error="대화 내용이 비어 있습니다.",
        )

    # 첫 사용자 메시지 = 핵심 요청
    user_prompt = ""
    detected_intent = ""
    for msg in messages:
        if msg.get("role") == "user":
            trace = msg.get("trace") or {}
            user_prompt = trace.get("user_prompt") or msg.get("content", "")
            detected_intent = trace.get("detected_intent", "")
            break

    # 첫 AI 응답에서 결과 추출
    generated_code = ""
    result_summary = ""
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        trace = msg.get("trace") or {}
        if not generated_code:
            generated_code = trace.get("generated_code", "")
        content = msg.get("content", "")
        if not result_summary:
            result_summary = _extract_result_shape(content)
        if generated_code:
            break

    # 코드가 trace에 없으면 마크다운 코드블록에서 추출
    if not generated_code:
        raw = path.read_text(encoding="utf-8")
        code_blocks = re.findall(r"```python\n(.*?)```", raw, re.DOTALL)
        if code_blocks:
            generated_code = code_blocks[0].strip()

    # 데이터 흐름 추적
    data_flow = DataFlowRecord()
    if generated_code:
        data_flow.files_used = _extract_files_from_code(generated_code)
        data_flow.columns_referenced = _extract_columns_from_code(generated_code)
        data_flow.operations = _extract_operations_from_code(generated_code)
    if result_summary:
        data_flow.output_shape = result_summary

    return StepContext(
        step_id=step_id,
        step_label=step_label,
        user_prompt=user_prompt.strip(),
        detected_intent=detected_intent,
        generated_code=generated_code,
        result_summary=result_summary,
        data_flow=data_flow,
        raw_messages=messages,
    )


# ── 이전 Step 컨텍스트 → 프롬프트 주입 ─────────────────────────

def build_step_context_prompt(prev_contexts: list[StepContext]) -> str:
    """이전 Step들의 결과를 다음 Step 프롬프트에 주입할 컨텍스트 텍스트를 생성합니다."""
    if not prev_contexts:
        return ""

    lines = ["[이전 단계 분석 결과]"]
    for ctx in prev_contexts:
        if not ctx.is_valid():
            continue
        lines.append(f"\n### {ctx.step_label}")
        lines.append(f"- 요청: {ctx.user_prompt[:200]}")
        if ctx.detected_intent:
            lines.append(f"- 분석 유형: {ctx.detected_intent}")
        if ctx.result_summary:
            lines.append(f"- 결과: {ctx.result_summary}")

        df = ctx.data_flow
        if df.columns_referenced:
            lines.append(f"- 사용된 컬럼: {', '.join(df.columns_referenced[:10])}")
        if df.operations:
            lines.append(f"- 수행된 연산: {', '.join(df.operations)}")
        if df.output_shape:
            lines.append(f"- 출력 형태: {df.output_shape}")

    lines.append(
        "\n위 결과를 참고하여 이번 단계의 분석을 이어서 진행하세요."
    )
    return "\n".join(lines)


# ── 데이터 흐름 시각화 텍스트 ─────────────────────────────────────

def build_data_flow_summary(steps: list[StepContext]) -> str:
    """Step 간 데이터 흐름을 요약하는 마크다운을 생성합니다."""
    if not steps:
        return ""

    lines = ["## 📊 데이터 흐름 추적\n"]

    for i, ctx in enumerate(steps):
        if not ctx.is_valid():
            continue
        df = ctx.data_flow
        lines.append(f"### {ctx.step_label}")
        lines.append(f"**요청**: {ctx.user_prompt[:100]}{'…' if len(ctx.user_prompt) > 100 else ''}")

        if df.files_used:
            lines.append(f"- 📂 입력 데이터: {', '.join(df.files_used)}")
        if df.columns_referenced:
            lines.append(f"- 📋 사용 컬럼: {', '.join(df.columns_referenced[:8])}")
        if df.operations:
            lines.append(f"- ⚙️ 연산: {', '.join(df.operations)}")
        if df.output_shape:
            lines.append(f"- 📤 출력: {df.output_shape}")

        # 다음 Step과의 연결 표시
        if i < len(steps) - 1:
            next_ctx = steps[i + 1]
            if next_ctx.is_valid():
                lines.append(f"\n  ⬇️ *{ctx.step_label} 결과* → *{next_ctx.step_label} 입력*으로 전달")
        lines.append("")

    return "\n".join(lines)


def build_data_flow_html(steps: list[StepContext]) -> str:
    """사이드바에 표시할 데이터 흐름 HTML을 생성합니다."""
    if not steps:
        return ""

    parts = ['<div class="sf-dataflow">']
    for i, ctx in enumerate(steps):
        if not ctx.is_valid():
            continue
        df = ctx.data_flow
        ops_text = ", ".join(df.operations[:3]) if df.operations else "—"
        cols_text = ", ".join(df.columns_referenced[:4]) if df.columns_referenced else "—"

        parts.append(
            f'<div class="sf-df-step">'
            f'<div class="sf-df-label">{ctx.step_label}</div>'
            f'<div class="sf-df-detail">컬럼: {cols_text}</div>'
            f'<div class="sf-df-detail">연산: {ops_text}</div>'
            f'<div class="sf-df-detail">출력: {df.output_shape or "—"}</div>'
            f'</div>'
        )
        if i < len(steps) - 1:
            parts.append('<div class="sf-df-arrow">⬇</div>')

    parts.append('</div>')
    return "\n".join(parts)


# ── Flow 실행 준비 ───────────────────────────────────────────────

def prepare_flow_execution(
    step_selections: dict[str, str],
    step_defs: list[tuple[str, str, str]],
    *,
    results_dir: Path | None = None,
) -> FlowExecutionResult:
    """선택된 Step 대화들의 컨텍스트를 추출하고 실행 계획을 준비합니다.

    Returns:
        FlowExecutionResult — steps에 각 StepContext가 채워진 상태.
        실제 재실행은 app.py에서 process_message를 호출하여 수행합니다.
    """
    result = FlowExecutionResult(
        flow_id=step_selections.get("flow_id", ""),
    )

    for step_key, step_label, _desc in step_defs:
        chat_file = step_selections.get(step_key, "")
        if not chat_file:
            result.steps.append(StepContext(
                step_id=step_key,
                step_label=step_label,
                error="대화가 선택되지 않았습니다.",
            ))
            continue

        ctx = extract_step_context(
            step_key, step_label, chat_file,
            results_dir=results_dir,
        )
        result.steps.append(ctx)

    valid_steps = [s for s in result.steps if s.is_valid()]
    if valid_steps:
        result.data_flow_summary = build_data_flow_summary(valid_steps)
        result.status = "ready"
    else:
        result.status = "no_valid_steps"

    return result


def get_step_prompt_with_context(
    current_step_index: int,
    steps: list[StepContext],
    *,
    attached_files: list[str] | None = None,
) -> str:
    """현재 Step의 프롬프트에 이전 Step 컨텍스트를 추가한 최종 프롬프트를 반환합니다.

    이것이 process_message()에 전달될 프롬프트입니다.
    """
    if current_step_index >= len(steps):
        return ""

    current = steps[current_step_index]
    if not current.is_valid():
        return ""

    prev_contexts = [
        s for s in steps[:current_step_index] if s.is_valid()
    ]

    if not prev_contexts:
        return current.user_prompt

    context_block = build_step_context_prompt(prev_contexts)
    return f"{context_block}\n\n[현재 요청]\n{current.user_prompt}"
