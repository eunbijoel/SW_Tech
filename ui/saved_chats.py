"""저장된 대화 목록 — 요약 제목 표시."""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from services.chat_catalog import format_chat_list_label


def render_saved_chats_section(
    saved_chats: list[dict],
    *,
    load_fn,
) -> None:
    """사이드바 「📜 저장된 대화」 — 요약 제목 리스트."""
    if not saved_chats:
        st.caption(
            "대화는 턴마다 자동 저장됩니다. "
            "목록에는 **스냅샷**만 표시됩니다 (📥 대화 저장 또는 동일 주제 갱신)."
        )
        return

    for item in saved_chats:
        fname = item["name"]
        label = format_chat_list_label(item)
        turns = item.get("turns", 0)

        st.markdown(
            f'<div class="saved-chat-row">'
            f'<span class="saved-chat-text" style="font-weight:600;">{html.escape(label)}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
        if turns:
            st.caption(f"`{fname}` · {turns}턴")

        c_load, c_dl, c_del = st.columns([2, 1, 1])
        with c_load:
            if st.button("불러오기", key=f"load_chat_top_{fname}", use_container_width=True):
                st.session_state.messages = load_fn(Path(item["path"]))
                st.session_state.active_chat_file = fname
                st.session_state.pending_excel_run = None
                st.session_state.pop("_excel_confirm_action", None)
                st.session_state.pop("_last_result_df", None)
                st.session_state.pop("_last_chart", None)
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
