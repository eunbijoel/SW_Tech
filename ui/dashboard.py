"""
센터장님 목업형 대시보드 UI — 시스템 모니터, Persona, Step Flow (Step 2).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from services.persona_store import get_persona, list_all_personas, save_custom_persona
from services.system_diagnostics import (
    SystemSnapshot,
    collect_system_snapshot,
    gpu_device_options,
)

FLOW_TEMPLATES_PATH = Path(__file__).resolve().parent.parent / "config" / "flow_templates.json"


def _card_css() -> None:
    st.markdown("""
<style>
.dash-card {
    background: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 12px;
    padding: 1rem 1.1rem;
    margin-bottom: 0.5rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.dash-card h4 { margin: 0 0 0.6rem 0; font-size: 0.95rem; color: #1d1d1f; }
.flow-step {
    background: #f5f5f7;
    border: 1px dashed #c7c7cc;
    border-radius: 8px;
    padding: 0.45rem 0.6rem;
    font-size: 0.82rem;
    text-align: center;
}
.flow-arrow { color: #86868b; font-size: 1.1rem; padding-top: 0.35rem; }
.status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.status-ok { background: #34c759; }
.status-bad { background: #ff3b30; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=8, show_spinner=False)
def _cached_snapshot(_disk_key: str) -> SystemSnapshot:
    return collect_system_snapshot(_disk_key or os.getcwd())


def render_page_title() -> None:
    st.markdown(
        '<h1 style="text-align:center;font-size:1.75rem;font-weight:700;'
        'color:#1d1d1f;margin:0.5rem 0 1.2rem 0;">Basic SW Technology</h1>',
        unsafe_allow_html=True,
    )


def render_system_monitor(snapshot: SystemSnapshot) -> None:
    st.markdown('<div class="dash-card">', unsafe_allow_html=True)
    st.markdown("#### 시스템 모니터")
    tab_gpu, tab_ram, tab_cpu, tab_disk = st.tabs(["GPU", "RAM", "CPU", "디스크"])

    with tab_gpu:
        if snapshot.gpus:
            for g in snapshot.gpus:
                st.markdown(f"**GPU{g.index}** · {g.name}")
                st.progress(g.memory_ratio, text=g.memory_label)
                if g.utilization_pct is not None:
                    st.caption(f"GPU 사용률 약 {g.utilization_pct:.0f}%")
        else:
            st.caption("GPU 정보 없음 (nvidia-smi 미설치 또는 드라이버 미연결)")

    with tab_ram:
        if snapshot.ram_total_gb > 0:
            ratio = snapshot.ram_used_gb / snapshot.ram_total_gb
            st.progress(
                min(1.0, ratio),
                text=f"{snapshot.ram_used_gb:.1f}/{snapshot.ram_total_gb:.1f} GB",
            )
        else:
            st.caption("RAM 정보를 읽을 수 없습니다.")

    with tab_cpu:
        st.metric("논리 CPU", snapshot.cpu_count)
        st.caption(f"Load average (1m): {snapshot.load_avg_1m:.2f}")

    with tab_disk:
        if snapshot.disk_total_gb > 0:
            ratio = snapshot.disk_used_gb / snapshot.disk_total_gb
            st.progress(
                min(1.0, ratio),
                text=f"{snapshot.disk_used_gb:.1f}/{snapshot.disk_total_gb:.1f} GB",
            )
            st.caption(f"경로: `{snapshot.disk_path}`")
        else:
            st.caption("디스크 정보 없음")

    st.markdown("</div>", unsafe_allow_html=True)


def render_server_status(snapshot: SystemSnapshot, selected_model: str) -> None:
    st.markdown('<div class="dash-card">', unsafe_allow_html=True)
    gpu_label = snapshot.gpus[0].name if snapshot.gpus else "NVIDIA / CPU"
    st.markdown(
        f'<p style="font-size:0.8rem;color:#6e6e73;margin:0;">GPU</p>'
        f'<p style="font-size:1.05rem;font-weight:600;margin:0.2rem 0 1rem 0;">{gpu_label}</p>',
        unsafe_allow_html=True,
    )
    st.markdown("##### 서버 상태")
    dot = "status-ok" if snapshot.ollama_connected else "status-bad"
    label = "Ollama 연결됨" if snapshot.ollama_connected else "Ollama 연결 안 됨"
    st.markdown(
        f'<span class="status-dot {dot}"></span>{label}',
        unsafe_allow_html=True,
    )
    st.caption(f"선택 모델: `{selected_model or '(없음)'}`")
    if snapshot.ollama_models:
        st.caption(f"설치 모델 {len(snapshot.ollama_models)}개")
    if snapshot.errors:
        for err in snapshot.errors[:2]:
            st.caption(f"⚠ {err}")
    st.markdown("</div>", unsafe_allow_html=True)


def render_dashboard_top(selected_model: str) -> SystemSnapshot:
    _card_css()
    snap = _cached_snapshot(os.getcwd())
    c1, c2 = st.columns([1.35, 1])
    with c1:
        render_system_monitor(snap)
    with c2:
        render_server_status(snap, selected_model)
    return snap


def render_persona_sidebar_section() -> None:
    """Persona JSON + UI 편집 (custom_personas.json)."""
    st.markdown("**🎭 페르소나**")
    all_personas = list_all_personas()
    labels = {p.id: f"{p.emoji} {p.name}" for p in all_personas}
    ids = list(labels.keys()) + ["__new__"]
    label_map = {**labels, "__new__": "➕ New persona"}

    current = st.session_state.get("persona_id", "general")
    if current not in ids:
        current = "general" if "general" in ids else ids[0]

    choice = st.selectbox(
        "페르소나",
        ids,
        index=ids.index(current) if current in ids else 0,
        format_func=lambda x: label_map[x],
        key="persona_id_select",
        label_visibility="collapsed",
    )
    st.session_state.persona_id = choice if choice != "__new__" else st.session_state.get(
        "persona_id", "general"
    )

    if choice == "__new__" or st.session_state.get("show_persona_form"):
        st.session_state.show_persona_form = True
        st.markdown("##### New persona")
        name = st.text_input("Persona name", placeholder="Work, Study, …", key="new_p_name")
        about = st.text_area(
            "About you",
            placeholder="What should the assistant know about you?",
            key="new_p_about",
            height=68,
        )
        style = st.text_area(
            "Response style",
            placeholder="Concise, technical, bullet points…",
            key="new_p_style",
            height=68,
        )
        c_save, c_cancel = st.columns(2)
        with c_save:
            if st.button("Save", type="primary", use_container_width=True, key="save_persona"):
                if name.strip():
                    p = save_custom_persona(name.strip(), about, style)
                    st.session_state.persona_id = p.id
                    st.session_state.show_persona_form = False
                    st.success(f"저장됨: {p.emoji} {p.name} → config/custom_personas.json")
                    st.rerun()
                else:
                    st.warning("Persona name을 입력하세요.")
        with c_cancel:
            if st.button("Cancel", use_container_width=True, key="cancel_persona"):
                st.session_state.show_persona_form = False
                st.rerun()
        st.caption("Step 3: 엑셀 코드 경로에도 Persona prompt 연동 예정")
    else:
        st.session_state.show_persona_form = False
        p = get_persona(st.session_state.persona_id)
        st.caption(f"_{p.description}_")
        with st.expander("JSON / system_prompt", expanded=False):
            st.caption("`config/custom_personas.json` + 내장 persona_service.py")
            st.text_area(
                "system_prompt",
                value=p.system_prompt[:2000],
                height=120,
                disabled=True,
                label_visibility="collapsed",
            )


def render_flow_sidebar_section() -> None:
    """Step Flow / Skill UI 골격 (실행 미연동)."""
    st.markdown("**🔗 Step Flow / Skill**")
    st.caption("STEP 1,2,3 순서로 stepwise 이어지는 구조 (Step 7 연동 예정)")

    flows: list[dict] = []
    if FLOW_TEMPLATES_PATH.exists():
        try:
            flows = json.loads(FLOW_TEMPLATES_PATH.read_text(encoding="utf-8")).get("flows", [])
        except json.JSONDecodeError:
            flows = []

    if not flows:
        st.info("flow_templates.json 없음")
        return

    flow_names = {f["id"]: f["name"] for f in flows}
    fid = st.selectbox(
        "Flow 템플릿",
        list(flow_names.keys()),
        format_func=lambda x: flow_names[x],
        key="selected_flow_id",
        label_visibility="collapsed",
    )
    flow = next(f for f in flows if f["id"] == fid)
    steps = flow.get("steps", [])
    if steps:
        cols = st.columns(len(steps) * 2 - 1)
        col_idx = 0
        for i, step in enumerate(steps):
            with cols[col_idx]:
                st.markdown(
                    f'<div class="flow-step"><b>{step.get("title", step["id"])}</b></div>',
                    unsafe_allow_html=True,
                )
            col_idx += 1
            if i < len(steps) - 1:
                with cols[col_idx]:
                    st.markdown('<div class="flow-arrow">→</div>', unsafe_allow_html=True)
                col_idx += 1
        st.caption(flow.get("description", ""))
    if st.button("▶ Flow 실행 (준비 중)", disabled=True, use_container_width=True):
        pass


def render_settings_section() -> None:
    with st.expander("⚙️ 설정 · 환경", expanded=False):
        st.markdown("**Preprocessing GPU (Step 2+)**")
        snap = _cached_snapshot(os.getcwd())
        opts = gpu_device_options(snap.gpus)
        st.selectbox(
            "Target GPU Device",
            opts,
            key="target_gpu_device",
            help="추후 전처리·Ollama GPU 할당에 연동 예정",
        )
        st.caption(f"CUDA_VISIBLE_DEVICES: `{snap.cuda_visible}`")
        st.markdown("**환경 변수**")
        st.code(
            f"OLLAMA_BASE_URL={os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}\n"
            f"STUDIO_PORT={os.getenv('STUDIO_PORT', '8502')}",
            language="bash",
        )
        st.caption("인트로/환경변수 편집 — Step 3에서 .env 연동 예정")
