"""
구조화된 프롬프트 생성 — 단순 문자열 붙이기 대신 섹션 분리.
"""
from __future__ import annotations

import json
from typing import Any

from src.persona_manager import PersonaProfile


def build_structured_sections(
    profile: PersonaProfile,
    user_request: str,
    *,
    intent: str,
    file_context: str = "",
    tool_context: dict[str, Any] | None = None,
    task_hint: str = "",
) -> dict[str, str]:
    """LLM·로그용 섹션 dict."""
    tool_json = ""
    if tool_context:
        tool_json = json.dumps(tool_context, ensure_ascii=False, indent=2)

    template_lines = "\n".join(
        f"  {i + 1}. {title}" for i, title in enumerate(profile.response_template)
    )
    focus_lines = "\n".join(f"- {f}" for f in profile.analysis_focus)

    return {
        "persona_role": (
            f"{profile.emoji} {profile.name}\n{profile.record.description}"
        ),
        "analysis_focus": focus_lines or "(기본 분석)",
        "system_instruction": profile.record.system_prompt.strip(),
        "response_style": profile.record.response_style or "structured_markdown",
        "response_template": template_lines or "  1. 요약\n  2. 상세",
        "style_rules": json.dumps(profile.style_rules, ensure_ascii=False),
        "detected_intent": intent,
        "task_hint": task_hint.strip(),
        "file_context": file_context.strip(),
        "tool_context": tool_json,
        "user_request": user_request.strip(),
    }


def build_chat_messages(
    sections: dict[str, str],
    *,
    include_tool_context: bool = True,
) -> list[dict[str, str]]:
    """Ollama chat API용 messages — system + user 분리."""
    system_parts = [
        "## Persona Role",
        sections["persona_role"],
        "",
        "## Analysis Focus",
        sections["analysis_focus"],
        "",
        "## System Instruction",
        sections["system_instruction"],
        "",
        "## Response Style",
        sections["response_style"],
        "",
        "## Required Output Sections",
        sections["response_template"],
        "",
        "## Style Rules",
        sections["style_rules"],
    ]
    if sections.get("task_hint"):
        system_parts.extend(["", "## Task Hint", sections["task_hint"]])

    user_parts = ["## User Request", sections["user_request"]]
    if sections.get("file_context"):
        user_parts.extend(["", "## File Context", sections["file_context"]])
    if include_tool_context and sections.get("tool_context"):
        user_parts.extend([
            "",
            "## Tool Execution Results (facts — use these, do not invent)",
            sections["tool_context"],
        ])

    return [
        {"role": "system", "content": "\n".join(system_parts)},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def build_code_generation_prompt(
    profile: PersonaProfile,
    user_request: str,
    data_context: str,
    *,
    intent: str,
    tool_context: dict[str, Any] | None = None,
    flags: dict[str, bool] | None = None,
    prev_error: str | None = None,
) -> str:
    """pandas 코드 생성 LLM용 — persona·tool 결과·데이터 컨텍스트 분리."""
    flags = flags or {}
    tool_block = ""
    if tool_context:
        tool_block = (
            "\n## Tool Results (verified facts)\n"
            + json.dumps(tool_context, ensure_ascii=False, indent=2)
            + "\n"
        )
    err_block = ""
    if prev_error:
        err_block = f"\n## Previous Error\n```\n{prev_error}\n```\n"

    focus = "\n".join(f"- {x}" for x in profile.analysis_focus[:6])
    template = "\n".join(
        f"{i + 1}. {t}" for i, t in enumerate(profile.response_template[:6])
    )

    return f"""You are generating pandas/numpy/matplotlib code for a {profile.name}.

## Persona Analysis Focus
{focus}

## Codegen Rules (must follow)
- Output ONLY executable Python. No markdown.
- Store result in variable `result` as DataFrame.
- Use only in-memory DataFrames: already loaded.
- Do NOT read files with pd.read_excel.
- Persona intent: {intent}
- merge allowed: {flags.get('allow_merge', True)}
- per_file mode: {flags.get('per_file_mode', False)}
- chart allowed: {flags.get('allow_chart', False)}

## Persona System Instruction
{profile.record.system_prompt.strip()}

{tool_block}
{err_block}
## Data Context
{data_context}

## User Request
{user_request.strip()}

## After execution, narrative should follow:
{template}
"""


def sections_to_preview_text(sections: dict[str, str]) -> str:
    """사이드바 미리보기용 — 섹션 구분 유지."""
    lines = ["=== Structured Prompt Preview ==="]
    for key in (
        "persona_role",
        "analysis_focus",
        "system_instruction",
        "task_hint",
        "detected_intent",
        "file_context",
        "tool_context",
        "user_request",
    ):
        val = sections.get(key, "")
        if val:
            lines.append(f"\n[{key}]\n{val[:2000]}")
    return "\n".join(lines)
