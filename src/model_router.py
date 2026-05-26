"""
구조화 프롬프트 → LLM 또는 mock 응답, Persona 템플릿으로 최종 포맷.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from src.persona_manager import PersonaProfile
from src.prompt_builder import build_chat_messages


def format_tool_response(
    profile: PersonaProfile,
    tool_results: dict[str, Any],
    *,
    user_prompt: str = "",
) -> str:
    """
    도구 실행 결과만으로 Persona response_template 형식의 마크다운 생성.
    (LLM 없이도 FILE_META / used range 질의에 답변 가능)
    """
    sections = list(profile.response_template)
    analysis = tool_results.get("excel_analyzer") or {}
    actions = tool_results.get("excel_actions") or {}
    files = analysis.get("files") or []

    parts: list[str] = []

    # 섹션 1: 파일/시트 구조 (또는 첫 템플릿 제목)
    title1 = sections[0] if sections else "요약"
    parts.append(f"### 1. {title1}")
    if not files:
        parts.append("- 첨부 파일 분석 결과가 없습니다.")
    for f in files:
        if f.get("error"):
            parts.append(f"- **{f.get('filename')}**: {f['error']}")
            continue
        parts.append(f"- 파일명: **{f.get('filename')}**")
        parts.append(f"- 시트(로드 기준): {f.get('sheet', 'Sheet1')}")
        cols = f.get("columns_sample") or []
        if cols:
            parts.append(f"- 컬럼 샘플: {', '.join(cols[:8])}{'…' if len(cols) > 8 else ''}")

    # 섹션 2: 데이터 범위
    title2 = sections[1] if len(sections) > 1 else "데이터 범위"
    parts.append(f"\n### 2. {title2}")
    for f in files:
        if f.get("error"):
            continue
        ur = f.get("used_range") or {}
        parts.append(f"**{f.get('filename')}**")
        parts.append(f"- 실제 입력 범위(추정): `{ur.get('range_a1', '—')}`")
        parts.append(f"- 사용 행 수: {ur.get('rows', '?')}")
        parts.append(f"- 사용 열 수: {ur.get('cols', '?')}")
        parts.append(f"- 비어 있지 않은 셀 수: {ur.get('filled_cells', '?')}")
        full = ur.get("full_shape") or {}
        if full:
            parts.append(
                f"- 전체 로드 shape: {full.get('rows')}행 × {full.get('cols')}열"
            )

    # 섹션 3: 정제 필요
    title3 = sections[2] if len(sections) > 2 else "정제 필요 항목"
    parts.append(f"\n### 3. {title3}")
    issues = []
    for f in files:
        if f.get("error"):
            continue
        ur = f.get("used_range") or {}
        if ur.get("empty_row_gaps", 0) > 0:
            issues.append(f"- {f.get('filename')}: 중간 빈 행 {ur['empty_row_gaps']}개 확인")
        if ur.get("missing_column_names", 0) > 0:
            issues.append(
                f"- {f.get('filename')}: Unnamed/누락 컬럼명 {ur['missing_column_names']}개 — 표준화 권장"
            )
        if f.get("null_pct", 0) > 10:
            issues.append(f"- {f.get('filename')}: 결측 비율 약 {f['null_pct']}%")
    if not issues:
        issues.append("- 현재 구조상 즉시 분석 가능 (치명적 정제 이슈 없음)")
    parts.extend(issues)

    # 섹션 4: 실행 단계
    title4 = sections[3] if len(sections) > 3 else "다음 단계"
    parts.append(f"\n### 4. {title4}")
    for act in actions.get("actions") or []:
        parts.append(f"- {act}")
    if user_prompt.strip():
        parts.append(f"\n> 요청: _{user_prompt.strip()[:200]}_")

    header = f"**{profile.emoji} {profile.name}** 분석 결과\n"
    return header + "\n".join(parts)


def generate_chat_response(
    profile: PersonaProfile,
    sections: dict[str, str],
    *,
    model: str,
    ollama_chat_fn: Callable[..., Any] | None = None,
) -> tuple[str, Any | None]:
    """실제 Ollama chat 호출. ollama_chat_fn 은 app.ollama_chat."""
    messages = build_chat_messages(sections)
    if ollama_chat_fn is None:
        return _mock_response(profile, sections), None
    result = ollama_chat_fn(model, messages)
    return result.content, result


def _mock_response(profile: PersonaProfile, sections: dict[str, str]) -> str:
    """API 없을 때 fallback."""
    return (
        f"**{profile.emoji} {profile.name}** (mock)\n\n"
        f"요청: {sections.get('user_request', '')[:300]}\n\n"
        f"도구 결과 요약:\n```\n{sections.get('tool_context', '')[:1500]}\n```"
    )


def format_codegen_explanation(
    profile: PersonaProfile,
    exec_result: dict[str, Any],
    tool_results: dict[str, Any] | None = None,
) -> str:
    """코드 실행 후 Persona 템플릿에 맞춘 짧은 설명 헤더."""
    template = profile.response_template
    lines = [f"**{profile.emoji} {profile.name}** 실행 결과\n"]
    if template:
        lines.append(f"### {template[0]}")
    shape = exec_result.get("shape")
    if shape:
        lines.append(f"- 결과 표: {shape.get('rows')}행 × {shape.get('cols')}열")
    if tool_results and "excel_analyzer" in tool_results:
        lines.append("- 도구 사전 분석 결과를 코드 실행에 반영했습니다.")
    return "\n".join(lines)
