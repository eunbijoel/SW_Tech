"""Step Flow / Skill — 저장된 대화를 Step 단위로 묶어 순차 실행하는 사이드바 UI."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import streamlit as st

from services.chat_catalog import format_step_select_label
from services.step_flow_engine import (
    FlowExecutionResult,
    StepContext,
    build_data_flow_html,
    prepare_flow_execution,
)

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
[data-testid="stSidebar"] .sf-node.running {
    color: #b35900;
    background: #fff8e6;
    border: 2px solid #ff9500;
    animation: sf-pulse 1.5s infinite;
}
@keyframes sf-pulse {
    0%, 100% { box-shadow: 0 0 0 1px rgba(255,149,0,0.15); }
    50% { box-shadow: 0 0 0 4px rgba(255,149,0,0.25); }
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
[data-testid="stSidebar"] .sf-dataflow {
    margin: 0.5rem 0;
    padding: 0.5rem;
    background: #fafafa;
    border-radius: 10px;
    border: 1px solid #e5e5ea;
}
[data-testid="stSidebar"] .sf-df-step {
    padding: 0.4rem 0.5rem;
    background: #fff;
    border-radius: 8px;
    border: 1px solid #e5e5ea;
    margin: 0.2rem 0;
}
[data-testid="stSidebar"] .sf-df-label {
    font-size: 0.75rem;
    font-weight: 700;
    color: #1d1d1f;
}
[data-testid="stSidebar"] .sf-df-detail {
    font-size: 0.68rem;
    color: #6e6e73;
    margin: 0.1rem 0;
}
[data-testid="stSidebar"] .sf-df-arrow {
    text-align: center;
    font-size: 0.9rem;
    color: #0071e3;
    padding: 0.1rem 0;
}
</style>
""",
        unsafe_allow_html=True,
    )


def _render_flowchart_nodes(
    step_flow: dict[str, str],
    running_step: str = "",
) -> None:
    """Step 노드 시각화. running_step이 설정되면 해당 노드에 running 효과."""
    nodes: list[str] = []
    for step_key, label, _desc in STEP_DEFS:
        val = step_flow.get(step_key, "")
        cls = "sf-node"
        if step_key == running_step:
            cls += " running"
        elif val:
            cls += " done"
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


def _count_selected_steps() -> int:
    """선택된 Step 수."""
    flow = st.session_state.get("step_flow", {})
    return sum(
        1 for key in ("step1", "step2", "step3")
        if flow.get(key) and flow[key] != FLOW_NONE
    )


def _render_data_flow_preview() -> None:
    """선택된 대화들의 데이터 흐름 미리보기."""
    flow = st.session_state.step_flow
    selected_count = _count_selected_steps()
    if selected_count < 1:
        return

    flow_result = prepare_flow_execution(
        flow,
        list(STEP_DEFS),
    )

    valid_steps = [s for s in flow_result.steps if s.is_valid()]
    if not valid_steps:
        return

    with st.expander("📊 데이터 흐름 미리보기", expanded=False):
        flow_html = build_data_flow_html(valid_steps)
        if flow_html:
            st.markdown(flow_html, unsafe_allow_html=True)

        for ctx in valid_steps:
            st.caption(f"**{ctx.step_label}**: {ctx.user_prompt[:80]}{'…' if len(ctx.user_prompt) > 80 else ''}")
            if ctx.data_flow.operations:
                st.caption(f"  연산: {', '.join(ctx.data_flow.operations[:4])}")


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

    running_step = st.session_state.get("flow_running_step", "")
    _render_flowchart_nodes(st.session_state.step_flow, running_step=running_step)

    if not saved_chats:
        st.caption("저장된 대화가 없습니다.")
    else:
        for step_key, step_label, desc in STEP_DEFS:
            render_step_card(step_key, step_label, desc, chat_options, label_map)

    # 데이터 흐름 미리보기
    _render_data_flow_preview()

    selected_count = _count_selected_steps()
    flow_in_progress = st.session_state.get("_flow_current_step_idx") is not None
    can_run = selected_count >= 2

    if flow_in_progress:
        _render_flow_progress_buttons(selected_count)
    else:
        st.caption("저장된 대화에서 Step을 고른 뒤 ▶ Flow 실행을 누르세요.")

        if st.button(
            f"▶ Flow 실행 ({selected_count}/3 Step 선택됨)",
            key="step_flow_run_btn",
            use_container_width=True,
            disabled=not can_run,
            type="primary" if can_run else "secondary",
        ):
            st.session_state["_flow_current_step_idx"] = 0
            st.session_state["_flow_execute_requested"] = True
            st.rerun()

        if not can_run and selected_count > 0:
            st.caption("최소 2개 Step을 선택해야 Flow를 실행할 수 있습니다.")

    # Flow 실행 결과가 있으면 표시
    flow_result = st.session_state.get("_flow_last_result")
    if flow_result and isinstance(flow_result, dict):
        _render_flow_result_summary(flow_result)


def _render_flow_progress_buttons(total_selected: int) -> None:
    """Flow 진행 중 — 다음 Step / 완료 / 중단 버튼."""
    current_idx = st.session_state.get("_flow_current_step_idx", 0)
    valid_cache = st.session_state.get("_flow_valid_steps_cache", [])
    total_valid = len(valid_cache) if valid_cache else total_selected

    if current_idx < total_valid:
        step_num = current_idx + 1
        st.success(f"Step {current_idx}/{total_valid} 완료")

        c1, c2 = st.columns(2)
        with c1:
            if st.button(
                f"▶ Step {step_num} 실행",
                key="step_flow_next_btn",
                use_container_width=True,
                type="primary",
            ):
                st.session_state["_flow_execute_requested"] = True
                st.rerun()
        with c2:
            if st.button(
                "⏹ Flow 중단",
                key="step_flow_stop_btn",
                use_container_width=True,
            ):
                _reset_flow_state()
                st.rerun()
    else:
        st.success(f"✅ 전체 {total_valid} Step 완료!")

        c1, c2 = st.columns(2)
        with c1:
            if st.button(
                "📊 흐름 요약",
                key="step_flow_summary_btn",
                use_container_width=True,
                type="primary",
            ):
                st.session_state["_flow_execute_requested"] = True
                st.rerun()
        with c2:
            if st.button(
                "🔄 새 Flow",
                key="step_flow_reset_btn",
                use_container_width=True,
            ):
                _reset_flow_state()
                st.rerun()


def _reset_flow_state() -> None:
    """Flow 실행 상태 초기화."""
    st.session_state.pop("_flow_current_step_idx", None)
    st.session_state.pop("_flow_valid_steps_cache", None)
    st.session_state.pop("flow_running_step", None)
    st.session_state.pop("_flow_last_result", None)


def _render_flow_result_summary(result: dict[str, Any]) -> None:
    """Flow 실행 완료 후 요약 표시."""
    with st.expander("✅ Flow 실행 결과", expanded=True):
        steps = result.get("steps", [])
        for step_info in steps:
            status_icon = "✅" if step_info.get("status") == "completed" else "⏭️"
            st.markdown(
                f"**{status_icon} {step_info.get('step_label', '')}**"
            )
            if step_info.get("prompt_preview"):
                st.caption(f"요청: {step_info['prompt_preview'][:100]}")
            if step_info.get("result_preview"):
                st.caption(f"결과: {step_info['result_preview']}")

        if result.get("data_flow_md"):
            st.markdown(result["data_flow_md"])


def get_step_flow_selection() -> dict[str, Any]:
    """실행 단계 연동용 — 현재 Step Flow 선택 스냅샷."""
    init_step_flow_state()
    return dict(st.session_state.step_flow)


# 하위 호환
render_step_flow_section = render_step_flow_sidebar
