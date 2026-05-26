"""
Persona 맞춤 분석 실행 오케스트레이터.

흐름:
  user_prompt → persona 로드 → file context → router → tools → prompt_builder → (model_router)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from services.prompt_enhancer import build_file_context, detect_intent
from src.model_router import format_tool_response
from src.persona_manager import PersonaProfile, load_persona_profile
from src.persona_router import AnalysisStrategy, decide_strategy
from src.prompt_builder import (
    build_structured_sections,
    build_code_generation_prompt,
    sections_to_preview_text,
)
from src.tool_registry import run_tools


@dataclass
class PersonaExecutionPlan:
    """process_message / generate_excel_code_only 가 소비하는 실행 계획."""

    profile: PersonaProfile
    strategy: AnalysisStrategy
    sections: dict[str, str]
    tool_results: dict[str, Any] = field(default_factory=dict)
    enhancement_meta: dict[str, Any] = field(default_factory=dict)
    enhancement_log: str = ""
    preview_text: str = ""
    structured_messages: list[dict[str, str]] = field(default_factory=list)
    execution_path: str = "llm_codegen"
    tool_formatted_markdown: str | None = None
    thinking_steps: list[dict[str, str]] = field(default_factory=list)

    def codegen_persona_addon(self) -> str:
        """generate_code_prompt 에 추가할 Persona 블록."""
        return build_code_generation_prompt(
            self.profile,
            self.sections.get("user_request", ""),
            "",  # data_context는 app 에서 붙임
            intent=self.strategy.intent,
            tool_context=self.tool_results,
            flags={},
        )


def prepare_persona_execution(
    user_prompt: str,
    persona_id: str,
    *,
    filenames: list[str],
    frames: dict[str, pd.DataFrame] | None = None,
    files_metadata: list[dict] | None = None,
    custom_system_prompt: str = "",
    use_enhancement: bool = True,
) -> PersonaExecutionPlan:
    """
    첨부 파일이 있을 때 Persona 파이프라인 전체를 준비합니다.

    use_enhancement=False 이면 도구·구조화는 최소화하고 system 만 유지합니다.
    """
    profile = load_persona_profile(persona_id, custom_system_prompt=custom_system_prompt)
    intent = detect_intent(user_prompt)
    task_hint = (profile.record.task_hints or {}).get(intent, "")

    strategy = decide_strategy(
        profile,
        intent,
        user_prompt,
        has_attachments=bool(filenames),
    )

    file_ctx = build_file_context(files_metadata or [])
    tool_results: dict[str, Any] = {}
    steps: list[dict[str, str]] = [
        {"label": "페르소나", "detail": f"{profile.emoji} {profile.name}"},
        {"label": "의도", "detail": intent},
        {"label": "실행 경로", "detail": strategy.execution_path},
    ]

    if use_enhancement and filenames and frames:
        steps.append({
            "label": "도구 실행",
            "detail": ", ".join(strategy.tools_to_run[:4]),
        })
        tool_results = run_tools(
            strategy.tools_to_run,
            filenames=filenames,
            frames=frames,
            user_prompt=user_prompt,
        )
        steps.append({
            "label": "도구 완료",
            "detail": ", ".join(tool_results.keys()),
        })

    sections = build_structured_sections(
        profile,
        user_prompt,
        intent=intent,
        file_context=file_ctx,
        tool_context=tool_results if tool_results else None,
        task_hint=task_hint,
    )

    preview = sections_to_preview_text(sections)
    tool_md: str | None = None
    if strategy.execution_path == "tool_response" and tool_results:
        tool_md = format_tool_response(profile, tool_results, user_prompt=user_prompt)

    from src.prompt_builder import build_chat_messages

    meta = {
        "persona_id": profile.id,
        "persona_name": profile.name,
        "persona_emoji": profile.emoji,
        "detected_intent": intent,
        "execution_path": strategy.execution_path,
        "tools_run": list(tool_results.keys()),
        "analysis_focus": profile.analysis_focus[:3],
    }
    log_parts = [
        f"페르소나: {profile.emoji} {profile.name}",
        f"의도: {intent}",
        f"경로: {strategy.execution_path}",
    ]
    if tool_results:
        log_parts.append(f"도구: {', '.join(tool_results.keys())}")

    return PersonaExecutionPlan(
        profile=profile,
        strategy=strategy,
        sections=sections,
        tool_results=tool_results,
        enhancement_meta=meta,
        enhancement_log=" | ".join(log_parts),
        preview_text=preview if use_enhancement else sections.get("user_request", ""),
        structured_messages=build_chat_messages(sections) if use_enhancement else [],
        execution_path=strategy.execution_path,
        tool_formatted_markdown=tool_md,
        thinking_steps=steps,
    )
