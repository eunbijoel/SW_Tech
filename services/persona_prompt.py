"""Persona + 사용자 Prompt 결합 — enhanced prompt 생성."""
from __future__ import annotations

from typing import Any

from services.persona_store import PersonaRecord, get_selected_persona


def build_enhanced_prompt(
    user_prompt: str,
    persona: PersonaRecord | None = None,
    *,
    persona_id: str | None = None,
    files_metadata: list[dict] | None = None,
    include_intent_hint: bool = True,
) -> str:
    """Persona instruction과 사용자 Prompt를 하나의 블록으로 결합."""
    from services.prompt_enhancer import build_file_context, detect_intent

    p = persona or get_selected_persona(persona_id or "general")
    user_prompt = user_prompt.strip()

    blocks = [
        "[Persona]",
        f"Name: {p.name}",
        f"Role: {p.description}",
        "",
        "[System Instruction]",
        p.system_prompt.strip(),
        "",
        "[Response Style]",
        p.response_style.strip() or "(기본 스타일)",
    ]

    if p.tools:
        blocks.extend(["", "[Tools]", ", ".join(p.tools)])

    if files_metadata:
        file_ctx = build_file_context(files_metadata)
        if file_ctx:
            blocks.extend(["", "[Attached Data]", file_ctx])

    if include_intent_hint and p.task_hints:
        intent = detect_intent(user_prompt)
        hint = p.task_hints.get(intent, "")
        if hint:
            blocks.extend(["", f"[Task Hint · {intent}]", hint])

    blocks.extend(["", "[User Request]", user_prompt])
    return "\n".join(blocks)


def build_enhancement_meta(
    user_prompt: str,
    persona: PersonaRecord,
    *,
    files_metadata: list[dict] | None = None,
) -> dict[str, Any]:
    """미리보기·로그용 메타."""
    from services.prompt_enhancer import detect_intent

    intent = detect_intent(user_prompt)
    return {
        "persona_id": persona.id,
        "persona_name": persona.name,
        "persona_emoji": persona.emoji,
        "description": persona.description,
        "system_prompt": persona.system_prompt,
        "response_style": persona.response_style,
        "detected_intent": intent,
        "file_count": len(files_metadata or []),
    }
