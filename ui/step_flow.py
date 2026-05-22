"""Step Flow / Skill — 저장된 대화를 Step 단위로 묶는 사이드바 UI."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import streamlit as st

from services.chat_catalog import format_step_select_label

ROOT = Path(__file__).resolve().parent.parent
FLOW_TEMPLATES_PATH = ROOT / "config" / "flow_templates.json"

FLOW_NONE = ""
FLOW_NEW_ID = "__new_flow__"

STEP_DEFS: tuple[tuple[str, str, str], ...] = (
    ("step1", "STEP 1", "입력/초기 분석"),
    ("step2", "STEP 2", "분석/생성"),
    ("step3", "STEP 3", "승인/실행 & Export"),
)


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def init_step_flow_state() -> None:
    """session_state['step_flow'] 초기화."""
    if "step_flow" not in st.session_state:
        st.session_state.step_flow = {
            "flow_id": "excel_stepwise",
            "step1": "",
            "step2": "",
            "step3": "",
        }
    flow = st.session_state.step_flow
    for key in ("step1", "step2", "step3"):
        flow.setdefault(key, "")
    flow.setdefault("flow_id", "excel_stepwise")


def get_saved_chat_options(
    saved_chats: list[dict],
) -> list[tuple[str, str]]:
    """selectbox용 (chat_filename, 요약 제목 라벨)."""
    options: list[tuple[str, str]] = [(FLOW_NONE, "(대화 선택)")]
    for item in saved_chats:
        options.append((item["name"], format_step_select_label(item)))
    return options


def _load_flow_templates() -> list[dict]:
    if not FLOW_TEMPLATES_PATH.exists():
        return []
    try:
        return json.loads(FLOW_TEMPLATES_PATH.read_text(encoding="utf-8")).get("flows", [])
    except json.JSONDecodeError:
        return []


def _chat_label_map(saved_chats: list[dict], options: list[tuple[str, str]]) -> dict[str, str]:
    m = {k: v for k, v in options}
    for item in saved_chats:
        title = item.get("title") or item.get("name", "")
        m.setdefault(item["name"], title)
    return m


def _step_flow_css() -> None:
    st.markdown(
        """
<style>
[data-testid="stSidebar"] .sf-wrap { margin: 0.25rem 0 0.5rem 0; }
[data-testid="stSidebar"] .sf-flow-row {
    display: flex;
    align-items: stretch;
    justify-content: space-between;
    gap: 0.2rem;
    margin: 0.65rem 0 0.85rem 0;
}
[data-testid="stSidebar"] .sf-node {
    flex: 1;
    min-width: 0;
    text-align: center;
    font-size: 0.68rem;
    font-weight: 600;
    color: #6e6e73;
    background: #f5f5f7;
    border: 1px solid #e5e5ea;
    border-radius: 10px;
    padding: 0.45rem 0.2rem;
    line-height: 1.25;
}
[data-testid="stSidebar"] .sf-node.done {
    color: #1d7a3c;
    background: #e8f8ee;
    border-color: #b8e6c8;
}
[data-testid="stSidebar"] .sf-node.active {
    color: #004080;
    background: #e8f4fd;
    border: 2px solid #0071e3;
    box-shadow: 0 0 0 1px rgba(0,113,227,0.15);
}
[data-testid="stSidebar"] .sf-arrow {
    flex: 0 0 auto;
    align-self: center;
    color: #c7c7cc;
    font-size: 0.75rem;
    padding: 0 0.05rem;
}
[data-testid="stSidebar"] .sf-card {
    background: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 12px;
    padding: 0.55rem 0.6rem 0.5rem;
    margin-bottom: 0.45rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
[data-testid="stSidebar"] .sf-card.active-step {
    border: 2px solid #0071e3;
    background: #f8fbff;
}
[data-testid="stSidebar"] .sf-card-title {
    font-size: 0.82rem;
    font-weight: 700;
    color: #1d1d1f;
    margin: 0 0 0.15rem 0;
}
[data-testid="stSidebar"] .sf-card-desc {
    font-size: 0.72rem;
    color: #86868b;
    margin: 0 0 0.35rem 0;
}
[data-testid="stSidebar"] .sf-picked {
    font-size: 0.72rem;
    color: #1d7a3c;
    background: #f0fdf4;
    border-radius: 6px;
    padding: 0.25rem 0.4rem;
    margin-top: 0.35rem;
    line-height: 1.3;
    word-break: break-all;
}
[data-testid="stSidebar"] .sf-picked.empty {
    color: #86868b;
    background: #f5f5f7;
}
</style>
""",
        unsafe_allow_html=True,
    )


def _render_flowchart_nodes(step_flow: dict[str, str]) -> None:
    nodes: list[str] = []
    for step_key, label, _desc in STEP_DEFS:
        val = step_flow.get(step_key, "")
        cls = "sf-node"
        if val:
            cls += " done"
        if step_key == "step2" and val:
            cls += " active"
        nodes.append(f'<div class="{cls}">{_esc(label)}</div>')

    arrows = '<span class="sf-arrow">→</span>'
    inner = arrows.join(nodes)
    st.markdown(
        f'<div class="sf-wrap"><div class="sf-flow-row">{inner}</div></div>',
        unsafe_allow_html=True,
    )


def render_step_card(
    step_key: str,
    step_label: str,
    description: str,
    options: list[tuple[str, str]],
    label_map: dict[str, str],
) -> None:
    """Step 카드 하나 + 저장 대화 selectbox."""
    init_step_flow_state()
    flow = st.session_state.step_flow
    ids = [o[0] for o in options]
    fmt = {k: v for k, v in options}

    current = flow.get(step_key, "")
    if current not in ids:
        current = FLOW_NONE
        flow[step_key] = FLOW_NONE

    is_active = step_key == "step2" and bool(current and current != FLOW_NONE)
    card_cls = "sf-card active-step" if is_active else "sf-card"

    st.markdown(
        f'<div class="{card_cls}">'
        f'<p class="sf-card-title">{_esc(step_label)}</p>'
        f'<p class="sf-card-desc">{_esc(description)}</p></div>',
        unsafe_allow_html=True,
    )

    selected = st.selectbox(
        step_label,
        ids,
        index=ids.index(current),
        format_func=lambda x: fmt.get(x, x),
        key=f"step_flow_select_{step_key}",
        label_visibility="collapsed",
    )
    flow[step_key] = selected

    if selected and selected != FLOW_NONE:
        summary = label_map.get(selected, selected)
        st.markdown(
            f'<p class="sf-picked">✓ {_esc(summary)}</p>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<p class="sf-picked empty">대화 미선택</p>', unsafe_allow_html=True)


def render_step_flow_sidebar(saved_chats: list[dict]) -> None:
    """전체 Step Flow / Skill 섹션 (사이드바)."""
    init_step_flow_state()
    _step_flow_css()

    st.markdown("**🔗 Step Flow / Skill**")

    flows = _load_flow_templates()
    flow_options: list[tuple[str, str]] = []
    for f in flows:
        flow_options.append((f["id"], f.get("name", f["id"])))
    flow_options.append((FLOW_NEW_ID, "새 Flow 만들기 (추후)"))

    flow_ids = [x[0] for x in flow_options]
    flow_labels = {x[0]: x[1] for x in flow_options}

    cur_flow = st.session_state.step_flow.get("flow_id", "excel_stepwise")
    if cur_flow not in flow_ids:
        cur_flow = flow_ids[0] if flow_ids else FLOW_NONE

    picked_flow = st.selectbox(
        "Flow 이름",
        flow_ids,
        index=flow_ids.index(cur_flow),
        format_func=lambda x: flow_labels.get(x, x),
        key="step_flow_name_select",
        label_visibility="collapsed",
    )
    st.session_state.step_flow["flow_id"] = picked_flow

    if picked_flow == FLOW_NEW_ID:
        st.caption("새 Flow 템플릿은 추후 지원 예정입니다.")

    chat_options = get_saved_chat_options(saved_chats)
    label_map = _chat_label_map(saved_chats, chat_options)

    _render_flowchart_nodes(st.session_state.step_flow)

    if not saved_chats:
        st.caption("저장된 대화가 없습니다.")
    else:
        for step_key, step_label, desc in STEP_DEFS:
            render_step_card(step_key, step_label, desc, chat_options, label_map)

    st.caption("저장된 대화에서 Step을 고른 뒤 불러오기 → 다음 Step으로 이어갑니다.")

    if st.button("▶ Flow 실행 (준비 중)", key="step_flow_run_btn", use_container_width=True):
        st.info("Flow 실행 기능은 다음 단계에서 구현 예정입니다.")


def get_step_flow_selection() -> dict[str, Any]:
    """실행 단계 연동용 — 현재 Step Flow 선택 스냅샷."""
    init_step_flow_state()
    return dict(st.session_state.step_flow)
