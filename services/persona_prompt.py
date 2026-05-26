"""Persona + 사용자 Prompt — 구조화 파이프라인 래퍼."""
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
    frames: dict | None = None,
    filenames: list[str] | None = None,
) -> str:
    """구조화 Persona 프롬프트 미리보기 텍스트 (레거시 API 호환)."""
    from src.persona_pipeline import prepare_persona_execution

    p = persona or get_selected_persona(persona_id or "general")
    fn = filenames or [m.get("name", "") for m in (files_metadata or []) if m.get("name")]
    plan = prepare_persona_execution(
        user_prompt.strip(),
        p.id,
        filenames=fn,
        frames=frames or {},
        files_metadata=files_metadata,
        use_enhancement=True,
    )
    return plan.preview_text


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
