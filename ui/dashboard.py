from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

import streamlit as st

from services.system_diagnostics import (
    SystemSnapshot,
    collect_system_snapshot,
    gpu_device_options,
)

ROOT = Path(__file__).resolve().parent.parent
FLOW_TEMPLATES_PATH = ROOT / "config" / "flow_templates.json"
_MONITOR_TABS = ("GPU", "RAM", "CPU", "디스크")


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _gpu_short_name(full_name: str) -> str:
    """NVIDIA GeForce RTX 5090 → RTX 5090"""
    name = full_name.strip()
    m = re.search(
        r"(RTX\s*\d+\s*\w*|GTX\s*\d+\s*\w*|GeForce\s+RTX\s*\d+\s*\w*)",
        name,
        re.I,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1).replace("GeForce ", "").strip())
    m = re.search(r"(Radeon\s+\w+)", name, re.I)
    if m:
        return m.group(1)
    return name.split()[-1] if name else "GPU"


def _gpu_vendor(full_name: str) -> str:
    low = full_name.lower()
    if "nvidia" in low or "geforce" in low or "rtx" in low or "gtx" in low:
        return "NVIDIA"
    if "amd" in low or "radeon" in low:
        return "AMD"
    if "intel" in low:
        return "Intel"
    return "GPU"


def _gpu_chip_label(full_name: str) -> str:
    """우측 카드 Server 값 — RTX 5090 → RTX5090"""
    short = _gpu_short_name(full_name)
    return re.sub(r"[^A-Za-z0-9]", "", short) or short


def _card_css() -> None:
    st.markdown("""
<style>
/* ── 시스템 모니터 (목업) ── */
/* Streamlit border 컨테이너 = 카드 외곽 (내용과 한 덩어리) */
section.main div[data-testid="stVerticalBlockBorderWrapper"] {
    background: #ffffff !important;
    border: 1px solid #e8e8ed !important;
    border-radius: 16px !important;
    padding: 1rem 1.2rem 1.1rem !important;
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}
.hw-card {
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0;
    box-shadow: none;
}
.mon-title-row {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    margin-bottom: 1rem;
}
.mon-title-row svg { flex-shrink: 0; }
.mon-title {
    font-size: 1rem;
    font-weight: 700;
    color: #1d1d1f;
    letter-spacing: -0.02em;
}
.mon-tabbar {
    display: flex;
    gap: 0.15rem;
    border-bottom: 1px solid #ececf0;
    margin-bottom: 1.15rem;
    padding-bottom: 0;
}
.mon-tab {
    flex: 1;
    text-align: center;
    font-size: 0.8rem;
    font-weight: 500;
    color: #86868b;
    padding: 0.55rem 0.25rem 0.65rem;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
}
.mon-tab.active {
    color: #1d1d1f;
    font-weight: 600;
    border-bottom-color: #34c759;
}
.mon-tab .tab-ico { display: block; font-size: 1rem; margin-bottom: 0.2rem; opacity: 0.55; }
.mon-tab.active .tab-ico { opacity: 1; }
.mon-body { min-height: 118px; }
.mon-row-top {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 0.5rem;
}
.mon-kicker {
    font-size: 0.78rem;
    color: #86868b;
    font-weight: 500;
    margin: 0;
}
.mon-badge {
    font-size: 0.72rem;
    font-weight: 600;
    color: #1d7a3c;
    background: #e8f8ee;
    border: 1px solid #b8e6c8;
    border-radius: 999px;
    padding: 0.22rem 0.55rem;
    white-space: nowrap;
}
.mon-device {
    font-size: 1.65rem;
    font-weight: 700;
    color: #1d1d1f;
    margin: 0.35rem 0 0.85rem 0;
    letter-spacing: -0.03em;
    line-height: 1.15;
}
.mon-bar-track {
    height: 10px;
    background: #ececf0;
    border-radius: 999px;
    overflow: hidden;
    margin-bottom: 0.55rem;
}
.mon-bar-fill {
    height: 100%;
    background: linear-gradient(90deg, #34c759 0%, #30d158 100%);
    border-radius: 999px;
    transition: width 0.3s ease;
}
.mon-foot {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.78rem;
    color: #6e6e73;
}
.mon-foot .live {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    color: #1d7a3c;
    font-weight: 500;
}
.mon-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #34c759;
    display: inline-block;
}
.mon-note {
    font-size: 0.72rem;
    color: #86868b;
    margin-top: 0.5rem;
    line-height: 1.35;
}
/* 우측 하드웨어 요약 */
.hw-card { padding: 0.85rem 1.1rem; }
.hw-row {
    display: flex;
    align-items: center;
    gap: 0.85rem;
    padding: 0.85rem 0;
}
.hw-row + .hw-row { border-top: 1px solid #f0f0f5; }
.hw-ico {
    width: 44px;
    height: 44px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}
.hw-ico.gpu { background: #e8f8ee; color: #1d7a3c; }
.hw-ico.srv { background: #f0ecff; color: #6b4fd9; }
.hw-ico.llm { background: #e8f4fd; color: #0071e3; }
.hw-label { font-size: 0.78rem; color: #86868b; margin: 0 0 0.15rem 0; }
.hw-value { font-size: 1.05rem; font-weight: 700; color: #1d1d1f; margin: 0; }
.hw-sub { font-size: 0.72rem; color: #6e6e73; margin: 0.15rem 0 0 0; }
/* Streamlit radio → 탭 스타일 (사이드바만 — 메인 모니터는 st.tabs 사용) */
[data-testid="stSidebar"] div[data-testid="stRadio"]:has(> label[data-baseweb="radio"]) {
    margin-top: -0.25rem;
}
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] {
    display: flex !important;
    flex-direction: row !important;
    gap: 0;
    width: 100%;
    border-bottom: 1px solid #ececf0;
    padding-bottom: 0.15rem;
}
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label {
    flex: 1 1 auto;
    justify-content: center;
    margin: 0 !important;
    padding: 0.5rem 0.15rem 0.55rem !important;
    border-bottom: 2px solid transparent;
    background: transparent !important;
    white-space: nowrap !important;
    min-width: fit-content;
}
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label[data-checked="true"] {
    border-bottom-color: #34c759 !important;
    font-weight: 600 !important;
}
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label > div:first-child {
    display: none !important;
}
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label > div:last-child,
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label p {
    font-size: 0.78rem !important;
    white-space: nowrap !important;
    word-break: keep-all !important;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
}
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] {
    flex-wrap: nowrap !important;
    overflow-x: auto;
}
/* 메인 시스템 모니터 탭 */
section.main [data-testid="stTabs"] { margin-top: 0.25rem; }
section.main [data-testid="stTabs"] button {
    font-size: 0.82rem !important;
    font-weight: 500 !important;
}
section.main [data-testid="stTabs"] button[aria-selected="true"] {
    color: #1d7a3c !important;
    border-bottom-color: #34c759 !important;
}
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
.saved-chat-row {
    background: #fff;
    border: 1px solid #e5e5ea;
    border-radius: 10px;
    padding: 0.5rem 0.65rem;
    margin: 0.35rem 0 0.25rem 0;
    font-size: 0.8rem;
    line-height: 1.35;
}
.saved-chat-time { color: #6e6e73; font-weight: 600; display: block; margin-bottom: 0.15rem; }
.saved-chat-text { color: #1d1d1f; }
.saved-chat-step {
    display: inline-block;
    margin-top: 0.25rem;
    font-size: 0.72rem;
    color: #0071e3;
    background: #e8f4fd;
    padding: 0.1rem 0.4rem;
    border-radius: 4px;
}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=8, show_spinner=False)
def _cached_snapshot(_root_key: str, _proj_key: str) -> SystemSnapshot:
    return collect_system_snapshot(disk_path="/", project_dir=_proj_key or str(ROOT))


def _monitor_metric(snapshot: SystemSnapshot, tab: str) -> dict[str, str | float | bool]:
    if tab == "GPU":
        if not snapshot.gpus:
            return {
                "kicker": "GPU",
                "name": "감지 안 됨",
                "badge": "—",
                "ratio": 0.0,
                "pct": 0.0,
                "in_use": False,
                "note": "nvidia-smi 미연결",
            }
        g = snapshot.gpus[0]
        used_gb = g.memory_used_mb / 1024
        total_gb = g.memory_total_mb / 1024
        total = round(total_gb)
        if used_gb < 1 and g.memory_used_mb > 0:
            badge = f"{g.memory_used_mb:.0f} MB / {total} GB"
        else:
            badge = f"{used_gb:.1f} / {total} GB"
        mem_pct = g.memory_ratio * 100.0
        util = (
            float(g.utilization_pct)
            if g.utilization_pct is not None
            else mem_pct
        )
        return {
            "kicker": "GPU",
            "name": _gpu_short_name(g.name),
            "badge": badge,
            "ratio": g.memory_ratio,
            "pct": mem_pct,
            "in_use": util > 3.0 or g.memory_ratio > 0.03,
            "note": _esc(g.name),
        }

    if tab == "RAM":
        if snapshot.ram_total_gb <= 0:
            return {
                "kicker": "RAM",
                "name": "정보 없음",
                "badge": "—",
                "ratio": 0.0,
                "pct": 0.0,
                "in_use": False,
                "note": "",
            }
        ratio = snapshot.ram_used_gb / snapshot.ram_total_gb
        return {
            "kicker": "RAM",
            "name": f"{snapshot.ram_total_gb:.0f} GB",
            "badge": f"{snapshot.ram_used_gb:.0f} / {snapshot.ram_total_gb:.0f} GB",
            "ratio": min(1.0, ratio),
            "pct": ratio * 100.0,
            "in_use": ratio > 0.05,
            "note": "시스템 메모리 (/proc/meminfo)",
        }

    if tab == "CPU":
        cores = snapshot.cpu_count or 0
        pct = snapshot.cpu_usage_pct
        return {
            "kicker": "CPU",
            "name": f"{cores} cores" if cores else "CPU",
            "badge": f"Load {snapshot.load_avg_1m:.2f}",
            "ratio": min(1.0, pct / 100.0),
            "pct": pct,
            "in_use": pct > 5.0,
            "note": f"Load 1m · {_esc(snapshot.hostname) or 'host'}",
        }

    # 디스크
    if snapshot.disk_total_gb <= 0:
        return {
            "kicker": "디스크",
            "name": "정보 없음",
            "badge": "—",
            "ratio": 0.0,
            "pct": 0.0,
            "in_use": False,
            "note": "",
        }
    ratio = snapshot.disk_used_gb / snapshot.disk_total_gb
    free_gb = snapshot.disk_total_gb - snapshot.disk_used_gb
    note = f"마운트 {_esc(snapshot.disk_mount_label)} · 여유 {free_gb:.1f} GB"
    if snapshot.project_dir_gb > 0:
        note += f" · 프로젝트 {snapshot.project_dir_gb:.2f} GB"
    warn = " · ⚠ 공간 부족" if ratio >= 0.9 else ""
    return {
        "kicker": "디스크",
        "name": "루트 파티션",
        "badge": f"{snapshot.disk_used_gb:.0f} / {snapshot.disk_total_gb:.0f} GB",
        "ratio": min(1.0, ratio),
        "pct": ratio * 100.0,
        "in_use": ratio > 0.01,
        "note": note + warn,
    }


def _monitor_body_html(metric: dict[str, str | float | bool]) -> str:
    ratio = float(metric["ratio"])
    pct = float(metric["pct"])
    fill = int(round(min(100, max(0, ratio * 100))))
    pct_label = int(round(pct))
    status = "사용 중" if metric["in_use"] else "대기"
    note = metric.get("note") or ""
    note_html = f'<p class="mon-note">{note}</p>' if note else ""
    return f"""
<div class="mon-body">
  <div class="mon-row-top">
    <p class="mon-kicker">{_esc(metric["kicker"])}</p>
    <span class="mon-badge">{_esc(metric["badge"])}</span>
  </div>
  <p class="mon-device">{_esc(metric["name"])}</p>
  <div class="mon-bar-track">
    <div class="mon-bar-fill" style="width:{fill}%;"></div>
  </div>
  <div class="mon-foot">
    <span class="live"><span class="mon-dot"></span>{status}</span>
    <span>{pct_label}% 사용률</span>
  </div>
  {note_html}
</div>
"""


_MONITOR_SVG = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" '
    'xmlns="http://www.w3.org/2000/svg">'
    '<rect x="2" y="3" width="20" height="14" rx="2" stroke="#34c759" stroke-width="1.8"/>'
    '<path d="M7 21h10M12 17v4" stroke="#34c759" stroke-width="1.8" stroke-linecap="round"/>'
    '<path d="M6 11h3l2-3 2 6 2-4 3 1" stroke="#34c759" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def render_system_monitor(snapshot: SystemSnapshot) -> None:
    # HTML div로 감싸면 Streamlit 위젯(tabs)이 밖으로 빠져 빈 박스만 보임 → container 사용
    with st.container(border=True):
        st.markdown(
            f'<div class="mon-title-row">{_MONITOR_SVG}'
            f'<span class="mon-title">시스템 모니터</span></div>',
            unsafe_allow_html=True,
        )

        tab_labels = {
            "GPU": "🎮 GPU",
            "RAM": "💾 RAM",
            "CPU": "⚙️ CPU",
            "디스크": "💿 디스크",
        }
        t_gpu, t_ram, t_cpu, t_disk = st.tabs([tab_labels[t] for t in _MONITOR_TABS])
        tab_panels = {
            "GPU": t_gpu,
            "RAM": t_ram,
            "CPU": t_cpu,
            "디스크": t_disk,
        }
        for tab_key, panel in tab_panels.items():
            with panel:
                metric = _monitor_metric(snapshot, tab_key)
                st.markdown(_monitor_body_html(metric), unsafe_allow_html=True)


def render_server_status(snapshot: SystemSnapshot, selected_model: str) -> None:
    if snapshot.gpus:
        vendor = _gpu_vendor(snapshot.gpus[0].name)
        chip = _gpu_chip_label(snapshot.gpus[0].name)
        gpu_full = snapshot.gpus[0].name
    else:
        vendor = "—"
        chip = snapshot.hostname or "Server"
        gpu_full = ""

    model_label = selected_model or "(미선택)"
    ollama_ok = snapshot.ollama_connected
    ollama_line = "연결됨" if ollama_ok else "연결 안 됨"
    model_count = len(snapshot.ollama_models)

    with st.container(border=True):
        st.markdown(
            f"""
<div class="hw-card">
<div class="hw-row">
  <div class="hw-ico gpu">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <rect x="4" y="4" width="16" height="16" rx="3" stroke="currentColor" stroke-width="1.8"/>
      <rect x="8" y="8" width="8" height="8" rx="1" stroke="currentColor" stroke-width="1.5"/>
    </svg>
  </div>
  <div>
    <p class="hw-label">GPU</p>
    <p class="hw-value">{_esc(vendor)}</p>
    <p class="hw-sub">{_esc(gpu_full[:48]) if gpu_full else "—"}</p>
  </div>
</div>
<div class="hw-row">
  <div class="hw-ico srv">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <rect x="3" y="4" width="18" height="6" rx="1.5" stroke="currentColor" stroke-width="1.8"/>
      <rect x="3" y="14" width="18" height="6" rx="1.5" stroke="currentColor" stroke-width="1.8"/>
      <circle cx="7" cy="7" r="1" fill="currentColor"/><circle cx="7" cy="17" r="1" fill="currentColor"/>
    </svg>
  </div>
  <div>
    <p class="hw-label">Server</p>
    <p class="hw-value">{_esc(chip)}</p>
    <p class="hw-sub">{_esc(snapshot.hostname)}</p>
  </div>
</div>
<div class="hw-row">
  <div class="hw-ico llm">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="8" r="3.5" stroke="currentColor" stroke-width="1.8"/>
      <path d="M5 19c0-3 3.1-5 7-5s7 2 7 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
    </svg>
  </div>
  <div>
    <p class="hw-label">LLM (Ollama)</p>
    <p class="hw-value">{_esc(model_label)}</p>
    <p class="hw-sub">{_esc(ollama_line)} · 설치 {model_count}개</p>
  </div>
</div>
</div>
""",
            unsafe_allow_html=True,
        )


def render_page_title() -> None:
    st.markdown(
        '<h1 style="text-align:center;font-size:1.75rem;font-weight:700;'
        'color:#1d1d1f;margin:0.5rem 0 1.2rem 0;">Basic SW Technology</h1>',
        unsafe_allow_html=True,
    )


def render_dashboard_top(selected_model: str) -> SystemSnapshot:
    _card_css()
    proj = str(ROOT)
    snap = _cached_snapshot("/", proj)
    c1, c2 = st.columns([1.55, 1])
    with c1:
        render_system_monitor(snap)
    with c2:
        render_server_status(snap, selected_model)
    return snap


def render_settings_section() -> None:
    snap = _cached_snapshot("/", str(ROOT))
    with st.expander("⚙️ 설정 · 환경", expanded=False):
        st.markdown("**Preprocessing GPU (Step 2+)**")
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
