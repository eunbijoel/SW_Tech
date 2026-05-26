"""
선택 Persona · 사용자 의도에 따른 분석 전략·도구·실행 경로 결정.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from src.persona_manager import PersonaProfile
from src.tool_registry import persona_allowed_tools

ExecutionPath = Literal["tool_response", "template_code", "llm_codegen"]


@dataclass
class AnalysisStrategy:
    """persona_router 출력 — 파이프라인이 따를 전략."""

    persona_id: str
    intent: str
    analysis_focus: list[str]
    response_template: list[str]
    tools_to_run: list[str]
    execution_path: ExecutionPath
    tool_response_eligible: bool
    codegen_focus: str


def decide_strategy(
    profile: PersonaProfile,
    intent: str,
    user_prompt: str,
    *,
    has_attachments: bool,
) -> AnalysisStrategy:
    """
    Persona tools + intent 로 도구 목록과 실행 경로를 결정합니다.

  - FILE_META + excel 계열 Persona → tool 우선, 가능 시 tool_response
  - CHART / MERGE / 복잡 분석 → llm_codegen
  - 집행률 표 등 → template_code (app 기존 builtin과 병행)
    """
    allowed = persona_allowed_tools(profile.tools)
    if not allowed:
        allowed = persona_allowed_tools(
            profile.record.tools or ["dataframe_summary"],
        )

    # Persona별 우선순위 정렬
    priority: dict[str, list[str]] = {
        "excel_expert": ["excel_analyzer", "excel_actions", "dataframe_summary"],
        "data_analyst": ["dataframe_summary", "statistics_analyzer", "excel_analyzer"],
        "business_consultant": ["kpi_summary", "insight_generator", "dataframe_summary"],
        "researcher": ["report_generator", "methodology_checker", "statistics_analyzer"],
        "general": ["basic_chat", "dataframe_summary"],
    }
    order = priority.get(profile.id, allowed)
    tools_to_run = [t for t in order if t in allowed]
    for t in allowed:
        if t not in tools_to_run:
            tools_to_run.append(t)

    # intent 별 추가 도구
    if intent == "FILE_META" and "excel_analyzer" in allowed:
        tools_to_run = ["excel_analyzer", "excel_actions"] + [
            t for t in tools_to_run if t not in ("excel_analyzer", "excel_actions")
        ]
    elif intent in ("ANALYSIS", "COMPARISON") and "statistics_analyzer" in allowed:
        if "statistics_analyzer" not in tools_to_run:
            tools_to_run.insert(0, "statistics_analyzer")
    elif intent == "MERGE" and "excel_analyzer" in allowed:
        tools_to_run = ["excel_analyzer", "dataframe_summary"] + tools_to_run

    range_meta = _is_range_meta_request(user_prompt)
    tool_response_eligible = (
        has_attachments
        and range_meta
        and profile.id in ("excel_expert", "general", "data_analyst")
        and "excel_analyzer" in tools_to_run
    )

    execution_path: ExecutionPath = "llm_codegen"
    if tool_response_eligible:
        execution_path = "tool_response"
    elif intent in ("CHART", "MERGE") or _needs_codegen(user_prompt):
        execution_path = "llm_codegen"
    elif intent == "FILE_META":
        execution_path = "template_code"

    codegen_focus = profile.analysis_focus[0] if profile.analysis_focus else "general analysis"

    return AnalysisStrategy(
        persona_id=profile.id,
        intent=intent,
        analysis_focus=list(profile.analysis_focus),
        response_template=list(profile.response_template),
        tools_to_run=tools_to_run[:5],
        execution_path=execution_path,
        tool_response_eligible=tool_response_eligible,
        codegen_focus=codegen_focus,
    )


def _is_range_meta_request(prompt: str) -> bool:
    """행·열 **범위/개수** 질의인지 판별 (집행률 등 '행' 포함 단어와 구분)."""
    t = prompt.replace(" ", "").lower()
    pl = prompt.lower()
    strong = (
        "범위",
        "몇행",
        "몇열",
        "usedrange",
        "for each",
        "각파일",
        "파일별",
        "입력된범위",
        "used range",
        "row count",
        "column count",
    )
    if any(k in t or k in pl for k in strong):
        return True
    # '행'/'열' + 숫자/개수/범위 맥락
    if ("행" in pl or "열" in pl) and any(
        w in pl for w in ("몇", "개수", "갯수", "범위", "count", "range", "입력")
    ):
        return True
    return False


def _needs_codegen(prompt: str) -> bool:
    t = prompt.lower()
    return any(
        k in t
        for k in ("차트", "그래프", "chart", "plot", "병합", "merge", "집행률", "visual")
    )
