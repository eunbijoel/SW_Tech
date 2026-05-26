"""
Persona JSON 로드/저장 및 스키마 보강.

- config/personas.json 읽기/쓰기 (services.persona_store 위임)
- analysis_focus, response_template, style_rules 등 확장 필드 기본값 채우기
- 내장 Persona 삭제 방지는 persona_store 가 담당
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.persona_store import (
    BUILTIN_IDS,
    PersonaRecord,
    create_persona,
    delete_persona,
    get_selected_persona,
    list_all_personas,
    load_personas,
    save_personas,
    update_persona,
)

# Persona별 기본 분석·출력·도구 프로필 (JSON에 없을 때 적용)
PERSONA_PROFILES: dict[str, dict[str, Any]] = {
    "data_analyst": {
        "analysis_focus": [
            "column structure",
            "statistical summary",
            "outliers",
            "patterns",
            "trends",
        ],
        "response_template": [
            "데이터 구조 요약",
            "주요 패턴",
            "이상치/주의점",
            "다음 분석 제안",
        ],
        "tools": ["dataframe_summary", "statistics_analyzer", "excel_analyzer"],
        "style_rules": {
            "tone": "analytical",
            "detail_level": "technical",
            "output_format": "structured_markdown",
        },
    },
    "excel_expert": {
        "analysis_focus": [
            "sheet structure",
            "used range",
            "merged cells",
            "empty rows and columns",
            "formula detection",
            "data cleaning",
        ],
        "response_template": [
            "파일/시트 구조",
            "입력된 데이터 범위",
            "정제 필요 항목",
            "실행 가능한 처리 단계",
        ],
        "tools": ["excel_analyzer", "excel_actions"],
        "style_rules": {
            "tone": "practical",
            "detail_level": "step_by_step",
            "output_format": "structured_markdown",
        },
    },
    "business_consultant": {
        "analysis_focus": [
            "KPI",
            "comparison tables",
            "decision points",
            "action items",
        ],
        "response_template": [
            "핵심 결론",
            "KPI 영향",
            "리스크",
            "실행 제안",
        ],
        "tools": ["kpi_summary", "insight_generator", "dataframe_summary"],
        "style_rules": {
            "tone": "executive",
            "detail_level": "concise",
            "output_format": "structured_markdown",
        },
    },
    "researcher": {
        "analysis_focus": [
            "methodology",
            "evidence",
            "limitations",
            "reproducibility",
            "report-style explanation",
        ],
        "response_template": [
            "분석 목적",
            "사용 데이터/방법",
            "결과",
            "한계 및 검증 필요사항",
        ],
        "tools": ["report_generator", "methodology_checker", "statistics_analyzer"],
        "style_rules": {
            "tone": "formal",
            "detail_level": "detailed",
            "output_format": "structured_markdown",
        },
    },
    "general": {
        "analysis_focus": [
            "clear summary",
            "balanced explanation",
            "next steps",
        ],
        "response_template": [
            "요약",
            "설명",
            "다음 단계",
        ],
        "tools": ["basic_chat", "dataframe_summary"],
        "style_rules": {
            "tone": "friendly",
            "detail_level": "balanced",
            "output_format": "structured_markdown",
        },
    },
}


@dataclass
class PersonaProfile:
    """실행 파이프라인용 확장 Persona 뷰."""

    record: PersonaRecord
    analysis_focus: list[str] = field(default_factory=list)
    response_template: list[str] = field(default_factory=list)
    style_rules: dict[str, str] = field(default_factory=dict)
    is_default: bool = False

    @property
    def id(self) -> str:
        return self.record.id

    @property
    def name(self) -> str:
        return self.record.name

    @property
    def emoji(self) -> str:
        return self.record.emoji

    @property
    def tools(self) -> list[str]:
        return list(self.record.tools)


def enrich_persona_record(rec: PersonaRecord, raw: dict[str, Any] | None = None) -> PersonaRecord:
    """JSON 확장 필드를 record에 반영 (없으면 프로필 기본값)."""
    raw = raw or {}
    profile = PERSONA_PROFILES.get(rec.id, {})

    if not rec.tools or rec.tools == ["pandas", "excel"]:
        rec.tools = list(profile.get("tools") or rec.tools)

    # 확장 필드는 동적 속성으로 attach (PersonaRecord dataclass 확장과 병행)
    return rec


def load_persona_profile(
    persona_id: str,
    *,
    custom_system_prompt: str = "",
) -> PersonaProfile:
    """선택 Persona + 확장 필드를 PersonaProfile 로 반환."""
    rec = get_selected_persona(persona_id)
    if custom_system_prompt.strip():
        rec = PersonaRecord(
            id=rec.id,
            name=rec.name,
            emoji=rec.emoji,
            description=rec.description,
            system_prompt=custom_system_prompt.strip(),
            response_style=rec.response_style,
            tools=list(rec.tools),
            task_hints=dict(rec.task_hints),
            builtin=rec.builtin,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
            analysis_focus=list(getattr(rec, "analysis_focus", []) or []),
            response_template=list(getattr(rec, "response_template", []) or []),
            style_rules=dict(getattr(rec, "style_rules", {}) or {}),
            is_default=rec.builtin,
        )

    rec = enrich_persona_record(rec)
    profile_defaults = PERSONA_PROFILES.get(rec.id, {})

    if not getattr(rec, "analysis_focus", None):
        rec.analysis_focus = list(profile_defaults.get("analysis_focus", []))
    if not getattr(rec, "response_template", None):
        rec.response_template = list(profile_defaults.get("response_template", []))
    if not getattr(rec, "style_rules", None):
        rec.style_rules = dict(profile_defaults.get("style_rules", {}))

    analysis_focus = list(rec.analysis_focus or profile_defaults.get("analysis_focus", []))
    response_template = list(rec.response_template or profile_defaults.get("response_template", []))
    style_rules = dict(rec.style_rules or profile_defaults.get("style_rules", {}))

    return PersonaProfile(
        record=rec,
        analysis_focus=analysis_focus,
        response_template=response_template,
        style_rules=style_rules,
        is_default=bool(getattr(rec, "is_default", rec.builtin)),
    )


# re-export CRUD for UI
__all__ = [
    "PersonaProfile",
    "PERSONA_PROFILES",
    "load_persona_profile",
    "load_personas",
    "save_personas",
    "list_all_personas",
    "create_persona",
    "update_persona",
    "delete_persona",
    "BUILTIN_IDS",
]
