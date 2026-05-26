"""
Persona JSON 저장소 — config/personas.json (내장 5종 + 사용자 편집/추가).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.persona_service import PERSONAS, Persona, get_persona as _get_builtin_fallback

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
PERSONAS_JSON_PATH = CONFIG_DIR / "personas.json"
LEGACY_CUSTOM_PATH = CONFIG_DIR / "custom_personas.json"

BUILTIN_IDS = frozenset(PERSONAS.keys())

_DEFAULT_RESPONSE_STYLES: dict[str, str] = {
    "data_analyst": "간결하고 기술적으로, bullet point 중심",
    "excel_expert": "단계별 설명, 코드·표 미리보기 포함",
    "business_consultant": "Executive Summary 우선, 경영 KPI 중심",
    "researcher": "목적→방법→결과→한계, 수치·단위 명시",
    "general": "친절하고 실용적, 필요 시 표·목록 활용",
}

_DEFAULT_TOOLS: dict[str, list[str]] = {
    "data_analyst": ["pandas", "excel", "chart"],
    "excel_expert": ["pandas", "excel"],
    "business_consultant": ["pandas", "excel", "kpi"],
    "researcher": ["pandas", "statistics"],
    "general": ["pandas", "excel"],
}


@dataclass
class PersonaRecord:
    id: str
    name: str
    description: str
    system_prompt: str
    response_style: str = ""
    tools: list[str] = field(default_factory=list)
    emoji: str = "🎯"
    task_hints: dict[str, str] = field(default_factory=dict)
    builtin: bool = False
    created_at: str = ""
    updated_at: str = ""
    # Persona 맞춤 분석 실행 (src/persona_manager 프로필과 동기)
    analysis_focus: list[str] = field(default_factory=list)
    response_template: list[str] = field(default_factory=list)
    style_rules: dict[str, str] = field(default_factory=dict)
    is_default: bool = False

    def to_persona(self) -> Persona:
        return Persona(
            id=self.id,
            name=self.name,
            emoji=self.emoji,
            description=self.description,
            system_prompt=self.system_prompt,
            task_hints=dict(self.task_hints),
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PersonaRecord:
        tools = data.get("tools") or []
        if isinstance(tools, str):
            tools = [t.strip() for t in tools.split(",") if t.strip()]
        builtin = bool(data.get("builtin", data.get("is_default", False)))
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            description=data.get("description", ""),
            system_prompt=data.get("system_prompt", "").strip()
            or _compose_system_from_legacy(data),
            response_style=data.get("response_style", "").strip(),
            tools=list(tools),
            emoji=data.get("emoji", "🎯"),
            task_hints=dict(data.get("task_hints") or {}),
            builtin=builtin,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            analysis_focus=list(data.get("analysis_focus") or []),
            response_template=list(data.get("response_template") or []),
            style_rules=dict(data.get("style_rules") or {}),
            is_default=bool(data.get("is_default", builtin)),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compose_system_from_legacy(data: dict[str, Any]) -> str:
    about = data.get("about_you", "").strip()
    style = data.get("response_style", "").strip()
    if not about and not style:
        return "당신은 친절한 AI 어시스턴트입니다."
    parts = ["당신은 사용자 맞춤 AI 어시스턴트입니다.", ""]
    if about:
        parts.append(f"[사용자 정보]\n{about}")
    if style:
        parts.append(f"[응답 스타일]\n{style}")
    parts.append("\n[출력 형식]\n- 한국어로 답변합니다.")
    return "\n".join(parts)


def _builtin_to_record(p: Persona) -> PersonaRecord:
    ts = _now_iso()
    return PersonaRecord(
        id=p.id,
        name=p.name,
        emoji=p.emoji,
        description=p.description,
        system_prompt=p.system_prompt,
        response_style=_DEFAULT_RESPONSE_STYLES.get(p.id, ""),
        tools=list(_DEFAULT_TOOLS.get(p.id, [])),
        task_hints=dict(p.task_hints),
        builtin=True,
        created_at=ts,
        updated_at=ts,
    )


def _seed_personas() -> list[PersonaRecord]:
    return [_builtin_to_record(p) for p in PERSONAS.values()]


def _slugify(name: str) -> str:
    s = re.sub(r"[^\w가-힣]+", "_", name.strip().lower())
    return s[:40] or "custom"


def ensure_personas_file() -> None:
    """personas.json 없으면 내장 5종으로 생성. legacy custom 병합."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if PERSONAS_JSON_PATH.exists():
        return

    records = _seed_personas()
    if LEGACY_CUSTOM_PATH.exists():
        try:
            legacy = json.loads(LEGACY_CUSTOM_PATH.read_text(encoding="utf-8"))
            items = legacy.get("personas", [])
            existing_ids = {r.id for r in records}
            for item in items:
                if isinstance(item, dict) and item.get("id") not in existing_ids:
                    records.append(PersonaRecord.from_dict({**item, "builtin": False}))
        except (json.JSONDecodeError, OSError):
            pass

    save_personas(records)


def load_personas() -> dict[str, PersonaRecord]:
    ensure_personas_file()
    try:
        raw = json.loads(PERSONAS_JSON_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {r.id: r for r in _seed_personas()}

    items = raw.get("personas", [])
    out: dict[str, PersonaRecord] = {}
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            rec = PersonaRecord.from_dict(item)
            if rec.id in BUILTIN_IDS:
                rec.builtin = True
            out[rec.id] = rec

    if not out:
        return {r.id: r for r in _seed_personas()}
    return out


def save_personas(personas: list[PersonaRecord] | dict[str, PersonaRecord]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if isinstance(personas, dict):
        persona_list = list(personas.values())
    else:
        persona_list = list(personas)

    builtin_order = list(PERSONAS.keys())
    custom_ids = sorted(p.id for p in persona_list if p.id not in BUILTIN_IDS)
    order = builtin_order + custom_ids
    ordered = []
    seen: set[str] = set()
    for pid in order:
        for p in persona_list:
            if p.id == pid and p.id not in seen:
                ordered.append(p)
                seen.add(p.id)
    for p in persona_list:
        if p.id not in seen:
            ordered.append(p)

    payload = {
        "personas": [p.to_dict() for p in ordered],
    }
    PERSONAS_JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_selected_persona(persona_id: str) -> PersonaRecord:
    personas = load_personas()
    return personas.get(persona_id, personas.get("general", _builtin_to_record(PERSONAS["general"])))


def list_all_personas() -> list[PersonaRecord]:
    personas = load_personas()
    builtin_order = list(PERSONAS.keys())
    custom = sorted(k for k in personas if k not in BUILTIN_IDS)
    return [personas[k] for k in builtin_order + custom if k in personas]


def get_persona(persona_id: str) -> Persona:
    """하위 호환 — Persona dataclass 반환."""
    return get_selected_persona(persona_id).to_persona()


def update_persona(record: PersonaRecord) -> PersonaRecord:
    personas = load_personas()
    if record.id in BUILTIN_IDS:
        record.builtin = True
    else:
        record.builtin = False
    if record.id in personas:
        record.created_at = personas[record.id].created_at or _now_iso()
    else:
        record.created_at = _now_iso()
    record.updated_at = _now_iso()
    personas[record.id] = record
    save_personas(personas)
    return record


def create_persona(
    name: str,
    description: str,
    system_prompt: str,
    response_style: str = "",
    tools: list[str] | None = None,
    emoji: str = "🎯",
) -> PersonaRecord:
    personas = load_personas()
    base_id = _slugify(name)
    pid = base_id
    n = 1
    while pid in personas:
        pid = f"{base_id}_{n}"
        n += 1
    record = PersonaRecord(
        id=pid,
        name=name.strip(),
        emoji=emoji,
        description=description.strip() or "사용자 정의 페르소나",
        system_prompt=system_prompt.strip() or "당신은 친절한 AI 어시스턴트입니다.",
        response_style=response_style.strip(),
        tools=tools or [],
        task_hints={},
        builtin=False,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    personas[pid] = record
    save_personas(personas)
    return record


def delete_persona(persona_id: str) -> bool:
    if persona_id in BUILTIN_IDS:
        return False
    personas = load_personas()
    if persona_id not in personas:
        return False
    del personas[persona_id]
    save_personas(personas)
    return True


def save_custom_persona(
    name: str,
    about_you: str,
    response_style: str,
    emoji: str = "🎯",
) -> Persona:
    """하위 호환 — about_you를 description/system에 반영."""
    desc = about_you.strip() or f"사용자 정의 · {name}"
    sp = (
        f"당신은 {name.strip()} 맥락에 맞는 AI 어시스턴트입니다.\n\n"
        f"[사용자 정보]\n{about_you}\n\n[응답 스타일]\n{response_style}"
        if about_you or response_style
        else "당신은 친절한 AI 어시스턴트입니다."
    )
    rec = create_persona(
        name=name,
        description=desc,
        system_prompt=sp,
        response_style=response_style,
        emoji=emoji,
    )
    return rec.to_persona()
