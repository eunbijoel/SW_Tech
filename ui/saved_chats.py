"""저장된 대화 목록 + Step Flow 연동."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
CHAT_STEP_LINKS_PATH = ROOT / "config" / "chat_step_links.json"
FLOW_TEMPLATES_PATH = ROOT / "config" / "flow_templates.json"


def _load_step_links() -> dict:
    if not CHAT_STEP_LINKS_PATH.exists():
        return {"flow_id": "excel_stepwise", "links": []}
    try:
        return json.loads(CHAT_STEP_LINKS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"flow_id": "excel_stepwise", "links": []}


def _load_flow_steps(flow_id: str) -> list[dict]:
    if not FLOW_TEMPLATES_PATH.exists():
        return []
    try:
        data = json.loads(FLOW_TEMPLATES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    for flow in data.get("flows", []):
        if flow.get("id") == flow_id:
            return flow.get("steps", [])
    return []


def _chat_step_map(links: list[dict]) -> dict[str, str]:
    return {x["chat"]: x["step_id"] for x in links if x.get("chat") and x.get("step_id")}


def render_saved_chats_section(
    saved_chats: list[dict],
    *,
    load_fn,
) -> None:
    """사이드바 「📜 저장된 대화」 바로 아래 — step 선택 + 대화 목록."""
    meta = _load_step_links()
    flow_id = meta.get("flow_id", "excel_stepwise")
    links = meta.get("links", [])
    step_by_chat = _chat_step_map(links)
    steps = _load_flow_steps(flow_id)

    step_labels: dict[str, str] = {}
    if steps:
        step_ids = [s["id"] for s in steps]
        step_labels = {s["id"]: s.get("title", s["id"]) for s in steps}
        if "flow_step_filter" not in st.session_state:
            st.session_state.flow_step_filter = step_ids[0] if step_ids else ""

        st.caption("Step별 대화 — 단계를 고른 뒤 아래에서 불러오기")
        st.radio(
            "Step",
            ["__all__"] + step_ids,
            format_func=lambda x: "전체 보기" if x == "__all__" else step_labels.get(x, x),
            key="flow_step_filter",
            horizontal=True,
            label_visibility="collapsed",
        )
        active_step = st.session_state.get("active_flow_step", "")
        if active_step:
            st.caption(f"현재 진행: **{step_labels.get(active_step, active_step)}**")

    if not saved_chats:
        st.caption("대화 저장(📥)을 누르면 results/ 에 목록이 쌓입니다.")
        return

    filter_step = st.session_state.get("flow_step_filter", "__all__")
    shown = 0
    for item in saved_chats:
        fname = item["name"]
        chat_step = step_by_chat.get(fname)
        if filter_step != "__all__" and chat_step and chat_step != filter_step:
            continue

        mtime_str = item["mtime"].strftime("%m/%d %H:%M")
        preview = item.get("preview") or fname
        if not preview:
            preview = fname

        step_html = ""
        if chat_step:
            step_title = step_labels.get(chat_step, chat_step)
            step_html = f'<span class="saved-chat-step">{step_title}</span>'
        st.markdown(
            f'<div class="saved-chat-row">'
            f'<span class="saved-chat-time">{mtime_str}</span>'
            f'<span class="saved-chat-text">{preview}</span>'
            f"{step_html}</div>",
            unsafe_allow_html=True,
        )

        c_load, c_dl, c_del = st.columns([2, 1, 1])
        with c_load:
            if st.button("불러오기", key=f"load_chat_top_{fname}", use_container_width=True):
                st.session_state.messages = load_fn(Path(item["path"]))
                st.session_state.pop("_last_result_df", None)
                st.session_state.pop("_last_chart", None)
                if chat_step:
                    st.session_state.active_flow_step = chat_step
                    idx = next(
                        (i for i, s in enumerate(steps) if s["id"] == chat_step),
                        -1,
                    )
                    if idx >= 0 and idx + 1 < len(steps):
                        st.session_state.flow_step_next = steps[idx + 1]["id"]
                st.rerun()
        with c_dl:
            try:
                st.download_button(
                    "⬇",
                    data=Path(item["path"]).read_bytes(),
                    file_name=fname,
                    mime="text/markdown",
                    key=f"dl_chat_top_{fname}",
                    use_container_width=True,
                )
            except Exception:
                pass
        with c_del:
            if st.button("🗑", key=f"del_chat_top_{fname}", use_container_width=True):
                Path(item["path"]).unlink(missing_ok=True)
                st.rerun()
        shown += 1

    if shown == 0:
        st.caption("이 Step에 연결된 저장 대화가 없습니다. 「전체 보기」를 선택하세요.")

    nxt = st.session_state.get("flow_step_next")
    if nxt and steps:
        nxt_title = step_labels.get(nxt, nxt)
        if st.button(f"▶ 다음 Step 이어서 ({nxt_title})", key="continue_next_step", use_container_width=True):
            st.session_state.flow_step_filter = nxt
            st.session_state.active_flow_step = nxt
            for item in saved_chats:
                if step_by_chat.get(item["name"]) == nxt:
                    st.session_state.messages = load_fn(Path(item["path"]))
                    st.session_state.pop("_last_result_df", None)
                    st.session_state.pop("_last_chart", None)
                    break
            st.rerun()
