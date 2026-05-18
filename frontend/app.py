"""
Basic Software Technology — ChatGPT/Gemini-style AI Chat

Single-page interface:
  • Dark sidebar  : new chat · model selector · file attach · saved conversations
  • Main area     : welcome screen (no messages) or chat bubbles
  • Bottom        : st.chat_input (always pinned)
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend.utils.api_client import (
    backend_health,
    chat_complete,
    chat_excel,
    delete_saved_chat,
    list_library_files,
    list_models,
    list_saved_chats,
    load_chat,
    save_chat,
    upload_files,
)
from frontend.utils.session import init_session

# ── Page config (must be the first Streamlit call) ───────────────────────────
st.set_page_config(
    page_title="Basic Software Technology",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_session()

# ── Extra session-state defaults ─────────────────────────────────────────────
_EXTRA_DEFAULTS: dict = {
    "pending_prompt": "",
    "chat_id": None,
    "selected_files": [],
    "selected_file_names": {},
}
for _k, _v in _EXTRA_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
/* ── Hide default Streamlit chrome ────────────────────────────────────── */
#MainMenu, header, footer { visibility: hidden; }

/* ── Hide auto-generated page navigation ─────────────────────────────── */
[data-testid="stSidebarNav"] { display: none; }

/* ── Dark sidebar ─────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #171717 !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown {
    color: #d1d1d1 !important;
}
[data-testid="stSidebar"] hr {
    border-color: #2e2e2e !important;
}
[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    color: #d1d1d1 !important;
    border: 1px solid #2e2e2e !important;
    border-radius: 8px !important;
    text-align: left !important;
    transition: background 0.15s;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: #2a2a2a !important;
    border-color: #444 !important;
}
[data-testid="stSidebar"] .stSelectbox > div,
[data-testid="stSidebar"] .stSelectbox label {
    color: #d1d1d1 !important;
}

/* ── Main content width & bottom padding (for chat_input) ─────────────── */
section.main .block-container {
    max-width: 820px;
    margin: 0 auto;
    padding-top: 2rem;
    padding-bottom: 110px;
}

/* ── Suggestion chip buttons ──────────────────────────────────────────── */
.chip-col .stButton > button {
    border-radius: 20px !important;
    border: 1px solid #e0e0e0 !important;
    background: #fafafa !important;
    color: #333 !important;
    font-size: 0.88rem !important;
    padding: 0.55rem 1.1rem !important;
    width: 100%;
    text-align: left;
    white-space: normal;
    height: auto;
    line-height: 1.4;
}
.chip-col .stButton > button:hover {
    background: #f0f0f0 !important;
    border-color: #bbb !important;
}

/* ── Chat bubbles ─────────────────────────────────────────────────────── */
[data-testid="stChatMessage"] {
    border-radius: 14px;
    margin-bottom: 6px;
}
</style>
""",
    unsafe_allow_html=True,
)

# ── Helper functions ──────────────────────────────────────────────────────────


def _get_models() -> list[str]:
    try:
        model_map = list_models()
        models = [m for names in model_map.values() for m in names]
        return models or ["gpt-4o"]
    except Exception:
        return ["gpt-4o", "gemini-1.5-pro", "llama3"]


def _save_current_chat() -> None:
    msgs = st.session_state.get("messages", [])
    if not msgs:
        return
    try:
        result = save_chat(
            messages=msgs,
            model=st.session_state.get("selected_model", "") or "",
            chat_id=st.session_state.get("chat_id"),
        )
        st.session_state.chat_id = result.get("id")
    except Exception:
        pass


def _new_chat() -> None:
    _save_current_chat()
    st.session_state.messages = []
    st.session_state.chat_id = None
    st.session_state.selected_files = []
    st.session_state.selected_file_names = {}


def _load_saved_chat(chat_id: str) -> None:
    try:
        data = load_chat(chat_id)
        st.session_state.messages = data.get("messages", [])
        st.session_state.chat_id = chat_id
        model = data.get("model", "")
        if model:
            st.session_state.selected_model = model
    except Exception:
        st.error("대화를 불러오지 못했습니다.")


def _format_excel_result(result: dict) -> str:
    if result.get("error"):
        return f"❌ **실행 오류**\n```\n{result['error']}\n```"

    parts: list[str] = []
    shape = result.get("result_shape")
    if shape:
        parts.append(f"✅ 분석 완료 — **{shape['rows']}행 × {shape['cols']}열**\n")

    preview = result.get("result_preview")
    if preview:
        df = pd.DataFrame(preview)
        parts.append(df.to_markdown(index=False))

    explanation = result.get("explanation", "")
    if explanation:
        parts.append(f"\n📝 {explanation}")

    code = result.get("code", "")
    if code:
        parts.append(
            f"\n<details><summary>생성된 pandas 코드 보기</summary>\n\n"
            f"```python\n{code}\n```\n</details>"
        )

    return "\n".join(parts) or "결과가 없습니다."


def _process_message(prompt: str) -> None:
    """Append user message, call AI, render assistant bubble, update session state."""
    if not prompt.strip():
        return

    st.session_state.messages.append({"role": "user", "content": prompt})

    model = st.session_state.get("selected_model", "") or ""
    selected_files: list[str] = st.session_state.get("selected_files", [])

    with st.chat_message("assistant"):
        with st.spinner("생각 중…"):
            try:
                if selected_files:
                    result = chat_excel(
                        file_ids=selected_files,
                        prompt=prompt,
                        model=model,
                    )
                    content = _format_excel_result(result)
                else:
                    resp = chat_complete(
                        messages=st.session_state.messages,
                        model=model,
                    )
                    content = resp.get("content", "응답을 받지 못했습니다.")
            except Exception as exc:
                content = f"⚠️ 오류가 발생했습니다: {exc}"

        st.markdown(content, unsafe_allow_html=True)

    st.session_state.messages.append({"role": "assistant", "content": content})


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 🤖 Basic Software Technology")
    st.caption("AI 채팅 플랫폼")
    st.divider()

    # ── New chat ──────────────────────────────────────────────────────────────
    if st.button("✏️  새 채팅", use_container_width=True, type="primary"):
        _new_chat()
        st.rerun()

    st.divider()

    # ── Model selector ────────────────────────────────────────────────────────
    st.markdown("**🧠 모델 선택**")
    available_models = _get_models()
    current_model = st.session_state.get("selected_model", available_models[0])
    if current_model not in available_models:
        available_models.insert(0, current_model)
    model_idx = available_models.index(current_model)

    st.selectbox(
        "모델",
        available_models,
        index=model_idx,
        key="selected_model",
        label_visibility="collapsed",
    )

    st.divider()

    # ── File attach ───────────────────────────────────────────────────────────
    st.markdown("**📎 파일 첨부**")

    with st.expander("+ 파일 업로드", expanded=False):
        raw_uploads = st.file_uploader(
            "Excel / CSV",
            type=["xlsx", "xls", "csv"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        if raw_uploads and st.button("첨부하기", key="attach_btn"):
            file_tuples = [(f.name, f.getvalue()) for f in raw_uploads]
            try:
                records = upload_files(
                    file_tuples,
                    session_id=st.session_state.get("session_id", ""),
                )
                for r in records:
                    fid = r["id"]
                    if fid not in st.session_state.selected_files:
                        st.session_state.selected_files.append(fid)
                        st.session_state.selected_file_names[fid] = r["original_name"]
                st.success(f"{len(records)}개 파일 첨부됨")
                st.rerun()
            except Exception as exc:
                st.error(f"업로드 실패: {exc}")

    # Library files (pre-seeded excel/ directory)
    try:
        library_files = list_library_files()
    except Exception:
        library_files = []

    if library_files:
        st.markdown("**📚 라이브러리**")
        for lf in library_files:
            fid = lf["id"]
            is_checked = fid in st.session_state.selected_files
            if st.checkbox(lf["original_name"], value=is_checked, key=f"lib_{fid}"):
                if fid not in st.session_state.selected_files:
                    st.session_state.selected_files.append(fid)
                    st.session_state.selected_file_names[fid] = lf["original_name"]
            else:
                if fid in st.session_state.selected_files:
                    st.session_state.selected_files.remove(fid)

    # Show selected files summary
    sel_files: list[str] = st.session_state.get("selected_files", [])
    if sel_files:
        names = [
            st.session_state.selected_file_names.get(fid, fid[:8])
            for fid in sel_files
        ]
        st.caption(f"선택됨: {', '.join(names)}")
        if st.button("선택 해제", key="clear_files_btn"):
            st.session_state.selected_files = []
            st.session_state.selected_file_names = {}
            st.rerun()

    st.divider()

    # ── Saved conversations ───────────────────────────────────────────────────
    st.markdown("**💬 저장된 대화**")

    try:
        saved_chats = list_saved_chats()
    except Exception:
        saved_chats = []

    if saved_chats:
        for chat_meta in saved_chats[:20]:
            cid = chat_meta["id"]
            label = chat_meta["title"]
            display = label[:30] + ("…" if len(label) > 30 else "")
            c1, c2 = st.columns([5, 1])
            with c1:
                if st.button(display, key=f"hist_{cid}", use_container_width=True):
                    _load_saved_chat(cid)
                    st.rerun()
            with c2:
                if st.button("✕", key=f"del_{cid}"):
                    try:
                        delete_saved_chat(cid)
                    except Exception:
                        pass
                    st.rerun()
    else:
        st.caption("저장된 대화가 없습니다")

    # Manual save button (only when chat is active)
    if st.session_state.get("messages"):
        st.divider()
        if st.button("💾 대화 저장", use_container_width=True):
            _save_current_chat()
            st.success("저장됨!")
            st.rerun()

    st.divider()

    # ── Backend status ────────────────────────────────────────────────────────
    healthy = backend_health()
    st.caption(f"{'🟢' if healthy else '🔴'} 백엔드 {'온라인' if healthy else '오프라인'}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN AREA
# ══════════════════════════════════════════════════════════════════════════════

SUGGESTIONS = [
    (
        "📊 월별 예산 현황 비교",
        "예실대비표 파일들의 월별 예산 집행 현황을 비교해서 분석해주세요.",
    ),
    (
        "📈 집행률 계산",
        "수정예산 합계 대비 당기도달액 합계의 집행률(%)을 계산하고 높은 순으로 정렬해주세요.",
    ),
    (
        "📋 잔액 상위 10개",
        "세출잔액이 가장 많은 상위 10개 항목을 추출해주세요.",
    ),
    (
        "💡 분석 방법 안내",
        "업로드된 예실대비표 엑셀 파일로 어떤 분석을 할 수 있는지 설명해주세요.",
    ),
]

messages: list[dict] = st.session_state.get("messages", [])
pending: str = st.session_state.get("pending_prompt", "")

# ── Handle pending prompt (chip click) — BEFORE rendering welcome/history ─────
if pending:
    st.session_state.pending_prompt = ""
    # Show existing messages first
    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"], unsafe_allow_html=True)
    # Show pending user message inline
    with st.chat_message("user"):
        st.markdown(pending)
    # Get AI response and update session state
    _process_message(pending)

elif not messages:
    # ── Welcome screen ────────────────────────────────────────────────────────
    st.markdown(
        """
<div style="text-align:center; margin-top:14vh; margin-bottom:2rem;">
    <h1 style="font-size:2.5rem; font-weight:700; color:#1a1a1a; margin-bottom:0.4rem;">
        Basic Software Technology
    </h1>
    <p style="color:#888; font-size:1.05rem;">
        AI에게 무엇이든 물어보세요
    </p>
</div>
""",
        unsafe_allow_html=True,
    )

    # Suggestion chips (2 × 2 grid)
    col_a, col_b = st.columns(2)
    for i, (label, prompt_text) in enumerate(SUGGESTIONS):
        target_col = col_a if i % 2 == 0 else col_b
        with target_col:
            st.markdown('<div class="chip-col">', unsafe_allow_html=True)
            if st.button(label, key=f"chip_{i}", use_container_width=True):
                st.session_state.pending_prompt = prompt_text
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

else:
    # ── Chat history ──────────────────────────────────────────────────────────
    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"], unsafe_allow_html=True)

# ── Chat input (always pinned to bottom by Streamlit) ────────────────────────
_model_label = st.session_state.get("selected_model", "auto") or "auto"
_sel = st.session_state.get("selected_files", [])
_file_label = f" · 파일 {len(_sel)}개 첨부" if _sel else ""
_placeholder = f"메시지 입력… (모델: {_model_label}{_file_label})"

if user_input := st.chat_input(_placeholder):
    with st.chat_message("user"):
        st.markdown(user_input)
    _process_message(user_input)
