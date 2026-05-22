"""
Persona JSON 저장소 — 내장 페르소나 + config/custom_personas.json (Step 2 UI).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict

from services.persona_service import PERSONAS, Persona, get_persona as _get_builtin

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CUSTOM_PERSONAS_PATH = CONFIG_DIR / "custom_personas.json"


def _slugify(name: str) -> str:
    s = re.sub(r"[^\w가-힣]+", "_", name.strip().lower())
    return s[:40] or "custom"


def _persona_from_dict(data: dict) -> Persona:
    about = data.get("about_you", "").strip()
    style = data.get("response_style", "").strip()
    base_prompt = data.get("system_prompt", "").strip()
    if not base_prompt and (about or style):
        parts = ["당신은 사용자 맞춤 AI 어시스턴트입니다.", ""]
        if about:
            parts.append(f"[사용자 정보]\n{about}")
        if style:
            parts.append(f"[응답 스타일]\n{style}")
        parts.append("\n[출력 형식]\n- 한국어로 답변합니다.")
        base_prompt = "\n".join(parts)
    return Persona(
        id=data["id"],
        name=data.get("name", data["id"]),
        emoji=data.get("emoji", "🎯"),
        description=data.get("description", "사용자 정의 페르소나"),
        system_prompt=base_prompt or "당신은 친절한 AI 어시스턴트입니다.",
        task_hints=data.get("task_hints", {}),
    )


def load_custom_personas() -> Dict[str, Persona]:
    if not CUSTOM_PERSONAS_PATH.exists():
        return {}
    try:
        raw = json.loads(CUSTOM_PERSONAS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    items = raw.get("personas", raw if isinstance(raw, list) else [])
    out: Dict[str, Persona] = {}
    for item in items:
        if not isinstance(item, dict) or "id" not in item:
            continue
        p = _persona_from_dict(item)
        out[p.id] = p
    return out


def save_custom_persona(
    name: str,
    about_you: str,
    response_style: str,
    emoji: str = "🎯",
) -> Persona:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    custom = load_custom_personas()
    base_id = _slugify(name)
    pid = base_id
    n = 1
    while pid in custom or pid in PERSONAS:
        pid = f"{base_id}_{n}"
        n += 1
    persona = _persona_from_dict({
        "id": pid,
        "name": name.strip(),
        "emoji": emoji,
        "description": f"사용자 정의 · {response_style[:40] or '맞춤 스타일'}",
        "about_you": about_you,
        "response_style": response_style,
        "task_hints": {},
    })
    custom[pid] = persona
    personas_list: list[dict] = []
    for p in custom.values():
        entry: dict = {
            "id": p.id,
            "name": p.name,
            "emoji": p.emoji,
            "description": p.description,
            "system_prompt": p.system_prompt,
            "task_hints": p.task_hints,
        }
        if p.id == persona.id:
            entry["about_you"] = about_you
            entry["response_style"] = response_style
        personas_list.append(entry)
    CUSTOM_PERSONAS_PATH.write_text(
        json.dumps({"personas": personas_list}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return persona


def list_all_personas() -> list[Persona]:
    merged = {**PERSONAS, **load_custom_personas()}
    builtin_order = list(PERSONAS.keys())
    custom_ids = [k for k in merged if k not in PERSONAS]
    return [merged[k] for k in builtin_order + sorted(custom_ids)]


def get_persona(persona_id: str) -> Persona:
    custom = load_custom_personas()
    if persona_id in custom:
        return custom[persona_id]
    return _get_builtin(persona_id)
