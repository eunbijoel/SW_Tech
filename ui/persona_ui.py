"""Persona 선택·편집·강화 Prompt 미리보기 UI."""
from __future__ import annotations

import streamlit as st

from services.persona_store import (
    BUILTIN_IDS,
    PersonaRecord,
    create_persona,
    delete_persona,
    get_selected_persona,
    list_all_personas,
    update_persona,
)


def _draft_key(persona_id: str) -> str:
    return f"persona_draft_{persona_id}"


def _load_draft(persona: PersonaRecord) -> dict[str, str]:
    key = _draft_key(persona.id)
    if key not in st.session_state:
        st.session_state[key] = {
            "name": persona.name,
            "description": persona.description,
            "system_prompt": persona.system_prompt,
            "response_style": persona.response_style,
            "tools": ", ".join(persona.tools),
        }
    return st.session_state[key]


def render_enhanced_prompt_preview(
    enhanced_prompt: str,
    meta: dict | None = None,
) -> None:
    """강화된 Prompt 미리보기."""
    if not enhanced_prompt:
        return

    with st.expander("✨ 강화된 Prompt 미리보기", expanded=False):
        if meta:
            st.caption(
                f"**{meta.get('persona_emoji', '')} {meta.get('persona_name', '')}** · "
                f"의도: `{meta.get('detected_intent', '')}`"
            )
            st.markdown("**System prompt**")
            st.text(meta.get("system_prompt", "")[:1200])
            st.markdown("**Response style**")
            st.caption(meta.get("response_style") or "(없음)")
        st.markdown("**최종 enhanced prompt**")
        st.code(enhanced_prompt[:4000], language=None)


def render_persona_sidebar() -> None:
    """Persona 선택·수정·저장 — 접이식(>) 사이드바."""
    with st.expander("🎭 페르소나", expanded=False):
        _render_persona_sidebar_content()


def _render_persona_sidebar_content() -> None:
    personas = list_all_personas()
    if not personas:
        st.warning("Persona 목록이 비어 있습니다.")
        return

    labels = {p.id: f"{p.emoji} {p.name}" for p in personas}
    ids = [p.id for p in personas] + ["__new__"]
    label_map = {**labels, "__new__": "➕ 새 Persona"}

    current = st.session_state.get("persona_id", "general")
    if current not in ids:
        current = "general"

    choice = st.selectbox(
        "Persona 선택",
        ids,
        index=ids.index(current) if current in ids else 0,
        format_func=lambda x: label_map.get(x, x),
        key="persona_id_select",
        label_visibility="collapsed",
    )

    if choice == "__new__":
        st.session_state.show_persona_form = True
        st.session_state.persona_id = current
    else:
        st.session_state.persona_id = choice
        st.session_state.show_persona_form = False

    if st.session_state.get("show_persona_form") or choice == "__new__":
        _render_new_persona_form()
        return

    persona = get_selected_persona(st.session_state.persona_id)
    draft = _load_draft(persona)

    st.caption(f"_{persona.description}_")
    if persona.builtin:
        st.caption("🔒 기본 Persona — 삭제 불가 · 내용 수정 후 Save 가능")

    draft["name"] = st.text_input("Persona name", value=draft["name"], key=f"pn_{persona.id}")
    draft["description"] = st.text_area(
        "Description",
        value=draft["description"],
        height=60,
        key=f"pd_{persona.id}",
    )
    draft["system_prompt"] = st.text_area(
        "System prompt",
        value=draft["system_prompt"],
        height=140,
        key=f"ps_{persona.id}",
        help="선택한 Persona의 시스템 지시문. Save 시 config/personas.json에 저장됩니다.",
    )
    draft["response_style"] = st.text_area(
        "Response style",
        value=draft["response_style"],
        height=56,
        key=f"pr_{persona.id}",
    )
    draft["tools"] = st.text_input(
        "Tools (쉼표 구분)",
        value=draft["tools"],
        key=f"pt_{persona.id}",
        placeholder="pandas, excel, chart",
    )

    c_save, c_del = st.columns(2)
    with c_save:
        if st.button("💾 Save", type="primary", use_container_width=True, key=f"save_p_{persona.id}"):
            tools = [t.strip() for t in draft["tools"].split(",") if t.strip()]
            updated = PersonaRecord(
                id=persona.id,
                name=draft["name"].strip() or persona.name,
                emoji=persona.emoji,
                description=draft["description"].strip(),
                system_prompt=draft["system_prompt"].strip(),
                response_style=draft["response_style"].strip(),
                tools=tools,
                task_hints=persona.task_hints,
                builtin=persona.builtin,
                created_at=persona.created_at,
                updated_at=persona.updated_at,
            )
            update_persona(updated)
            st.session_state.pop(_draft_key(persona.id), None)
            st.session_state.custom_system_prompt = updated.system_prompt
            st.success(f"저장됨 → `config/personas.json`")
            st.rerun()
    with c_del:
        if persona.id in BUILTIN_IDS:
            st.button("🗑 삭제", disabled=True, use_container_width=True, key=f"del_dis_{persona.id}")
        elif st.button("🗑 삭제", use_container_width=True, key=f"del_p_{persona.id}"):
            delete_persona(persona.id)
            st.session_state.persona_id = "general"
            st.session_state.pop(_draft_key(persona.id), None)
            st.rerun()


def _render_new_persona_form() -> None:
    st.markdown("##### 새 Persona")
    name = st.text_input("Persona name", key="new_p_name")
    desc = st.text_area("Description", key="new_p_desc", height=56)
    sp = st.text_area("System prompt", key="new_p_sp", height=100)
    style = st.text_area("Response style", key="new_p_style", height=56)
    tools = st.text_input("Tools", key="new_p_tools", placeholder="pandas, excel")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("추가", type="primary", use_container_width=True, key="add_persona"):
            if not name.strip():
                st.warning("이름을 입력하세요.")
            else:
                tool_list = [t.strip() for t in tools.split(",") if t.strip()]
                rec = create_persona(
                    name=name,
                    description=desc or name,
                    system_prompt=sp or "당신은 친절한 AI 어시스턴트입니다.",
                    response_style=style,
                    tools=tool_list,
                )
                st.session_state.persona_id = rec.id
                st.session_state.show_persona_form = False
                st.success(f"추가됨: {rec.emoji} {rec.name}")
                st.rerun()
    with c2:
        if st.button("취소", use_container_width=True, key="cancel_new_persona"):
            st.session_state.show_persona_form = False
            st.rerun()


# 하위 호환
render_persona_sidebar_section = render_persona_sidebar
