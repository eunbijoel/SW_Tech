"""
Basic SW Technology — Streamlit 기반 AI 엑셀 분석 도구
Ollama 로컬 모델을 활용한 자연어 엑셀 처리·분석·병합·내보내기
"""
from __future__ import annotations

import ast
import datetime
import io
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests
import streamlit as st

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
EXCEL_DIR = Path("./excel")
RESULTS_DIR = Path("./results")
EXCEL_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

# 채팅·미리보기 표 표시 크기
TABLE_PREVIEW_ROWS = 10
TABLE_PREVIEW_HEIGHT = 200

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")  # 모델을 GPU/RAM에 유지

# 응답 속도용 — num_predict·num_ctx 제한 (기본 32k는 느림)
OLLAMA_OPTS_CODE: dict[str, Any] = {
    "num_predict": 2048,
    "num_ctx": 8192,
}
OLLAMA_OPTS_EXPLAIN: dict[str, Any] = {
    "num_predict": 400,
    "num_ctx": 4096,
}
OLLAMA_OPTS_CHAT: dict[str, Any] = {
    "num_predict": 1024,
    "num_ctx": 4096,
}

# Gemma4 등 thinking 모델 — think 미설정 시 num_predict가 추론에만 쓰이고 content가 비는 경우 있음
_THINKING_MODEL_HINTS = ("gemma4", "gemma3", "qwen3", "deepseek-r1", "r1")


def _ollama_payload_think(model: str, *, force_no_think: bool = False) -> dict[str, Any]:
    """Ollama /api/chat 의 think 플래그. False면 추론 생략 후 content에 바로 출력."""
    n = (model or "").lower()
    if force_no_think or any(h in n for h in _THINKING_MODEL_HINTS):
        return {"think": False}
    return {}

# 작은 모델을 먼저 — qwen3-coder:30b 등은 RAM 부족 시 Ollama 500 오류
PREFERRED_MODELS = [
    "qwen2.5:7b",
    "llama3",
    "gemma2",
    "phi3",
    "deepseek-coder-v2",
    "qwen3-coder:30b",
]

# ─── 페이지 설정 ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Basic SW Technology",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── 세션 초기화 ──────────────────────────────────────────────────────────────
_DEFAULTS: dict[str, Any] = {
    "messages": [],
    "selected_model": "",
    "attached_files": [],          # list of filenames
    "pending_prompt": "",
    "persona_id": "general",
    "use_enhancement": True,
    "custom_system_prompt": "",
    "fast_mode": True,              # True: 코드 1회만 (설명 LLM 생략)
    "ollama_warmed": False,
    "show_persona_form": False,
    "target_gpu_device": "GPU0 (기본)",
    "chat_session_id": "",
    "active_chat_file": "",
    "pending_excel_run": None,
    "auto_run_excel_code": False,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ─── CSS (라이트 테마) ────────────────────────────────────────────────────────
st.markdown("""
<style>
#MainMenu, header, footer { visibility: hidden; }
[data-testid="stSidebarNav"] { display: none; }

[data-testid="stSidebar"] {
    background-color: #f5f5f7 !important;
    border-right: 1px solid #e5e5ea !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown {
    color: #1d1d1f !important;
}
[data-testid="stSidebar"] hr { border-color: #e5e5ea !important; }
[data-testid="stSidebar"] .stButton > button {
    background: #ffffff !important;
    color: #1d1d1f !important;
    border: 1px solid #d2d2d7 !important;
    border-radius: 8px !important;
    transition: background 0.15s;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: #ebebef !important;
    border-color: #b8b8bd !important;
}

section.main { background-color: #ffffff !important; }
section.main .block-container {
    max-width: 920px;
    margin: 0 auto;
    padding-top: 2rem;
    padding-bottom: 110px;
}
section.main p,
section.main .stMarkdown,
section.main label {
    color: #31333f !important;
}

[data-testid="stChatMessage"] {
    border-radius: 14px;
    margin-bottom: 6px;
}
[data-testid="stChatMessage"] p,
[data-testid="stChatMessage"] .stMarkdown {
    color: #31333f !important;
}

[data-testid="stChatInput"] textarea {
    background-color: #f5f5f7 !important;
    color: #1d1d1f !important;
    border: 1px solid #d2d2d7 !important;
}

.chip-col .stButton > button {
    border-radius: 20px !important;
    border: 1px solid #d2d2d7 !important;
    background: #f5f5f7 !important;
    color: #1d1d1f !important;
    font-size: 0.88rem !important;
    padding: 0.55rem 1.1rem !important;
    width: 100%;
    text-align: left;
    white-space: normal;
    height: auto;
    line-height: 1.4;
}
.chip-col .stButton > button:hover {
    background: #ebebef !important;
    border-color: #b8b8bd !important;
}

/* 결과 표 — 작게 + 스크롤 */
[data-testid="stChatMessage"] [data-testid="stDataFrame"],
[data-testid="stSidebar"] [data-testid="stDataFrame"] {
    font-size: 0.78rem !important;
}
[data-testid="stChatMessage"] [data-testid="stDataFrame"] div {
    max-height: 220px;
}
[data-testid="stChatMessage"] table {
    font-size: 0.78rem !important;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# OLLAMA 연결
# ══════════════════════════════════════════════════════════════════════════════

def ollama_health() -> bool:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _model_matches_installed(preferred: str, installed: str) -> bool:
    """'deepseek-coder-v2' ↔ 'deepseek-coder-v2:latest' 등 이름 변형 허용."""
    if preferred == installed:
        return True
    return installed.startswith(preferred + ":") or preferred.startswith(installed + ":")


_HEAVY_MODEL_HINTS = ("30b", "32b", "34b", "70b", "27b", "31b", "65b", "gpt-oss", "120b")


def is_heavy_ollama_model(model: str) -> bool:
    """RAM 32GB 이하 환경에서 OOM 나기 쉬운 모델."""
    n = model.lower()
    return any(h in n for h in _HEAVY_MODEL_HINTS)


def _ollama_show_model(name: str) -> dict[str, Any] | None:
    """Ollama /api/show — VRAM 추정용."""
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/show",
            json={"name": name},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _parse_param_billions(param_size: str) -> float | None:
    m = re.search(r"([\d.]+)\s*[Bb]", param_size)
    if m:
        return float(m.group(1))
    m = re.search(r"([\d.]+)\s*[Mm]", param_size)
    if m:
        return float(m.group(1)) / 1000
    return None


def _parse_quant_bits(quant_level: str) -> float:
    if not quant_level:
        return 16.0
    q = quant_level.upper()
    if "Q2" in q:
        return 2.5
    if "Q3" in q:
        return 3.5
    if "Q4" in q:
        return 4.5
    if "Q5" in q:
        return 5.5
    if "Q6" in q:
        return 6.5
    if "Q8" in q:
        return 8.0
    if "F16" in q or "FP16" in q:
        return 16.0
    if "F32" in q or "FP32" in q:
        return 32.0
    return 4.5


def _estimate_model_vram_gb(model_name: str) -> float | None:
    data = _ollama_show_model(model_name)
    if not data:
        return None
    details = data.get("details", {})
    param_size = details.get("parameter_size", "")
    params_b = _parse_param_billions(param_size)
    if params_b is None:
        return None
    bits = _parse_quant_bits(details.get("quantization_level", ""))
    return round(params_b * bits / 8 * 1.2, 1)


def model_fits_gpu(model: str, snap: Any) -> bool | None:
    """True=GPU VRAM 충분, False=부족, None=판단 불가."""
    if not model or not getattr(snap, "gpus", None):
        return None
    estimated = _estimate_model_vram_gb(model)
    if estimated is None:
        return None
    available_gb = snap.gpus[0].memory_total_mb / 1024
    return estimated <= available_gb


def sidebar_model_notice(
    model: str,
    snap: Any,
    *,
    has_excel_files: bool,
) -> str | None:
    """대형 모델 선택 시 사이드바 안내 — None이면 표시 안 함."""
    if not model or model == "(없음)":
        return None
    if not is_heavy_ollama_model(model):
        return None

    fits = model_fits_gpu(model, snap)
    if fits is True:
        if has_excel_files:
            return (
                f"`{model}` — GPU VRAM 충분합니다. "
                "엑셀 pandas 코드는 **qwen2.5:7b** · **qwen3-coder** 가 더 안정적입니다. "
                "(Gemma4는 thinking·용량 때문에 느리거나 빈 응답이 날 수 있음)"
            )
        if "gemma4" in model.lower():
            return (
                f"`{model}` — thinking 모델입니다. "
                "엑셀 분석·코드 생성은 **qwen2.5:7b** 권장."
            )
        return None

    if fits is False and snap.gpus:
        g = snap.gpus[0]
        return (
            f"`{model}` 은 이 GPU({g.memory_label})에 맞지 않을 수 있습니다. "
            "qwen2.5:7b 또는 더 작은 모델을 권장합니다."
        )

    return (
        f"`{model}` 은 용량이 큰 모델입니다. "
        "Ollama 실행 시 RAM/VRAM을 확인하세요."
    )


def pick_safe_ollama_model(
    model: str,
    available: list[str],
    snap: Any | None = None,
) -> str:
    """대형 모델 — GPU VRAM이 충분하면 사용자 선택 유지, 아니면 경량 모델로 대체."""
    if model and not is_heavy_ollama_model(model):
        return model
    if snap is not None and model_fits_gpu(model, snap) is True:
        return model
    for candidate in ("qwen2.5:7b", "llama3", "gemma2", "phi3"):
        for m in available:
            if m == candidate or m.startswith(candidate + ":"):
                return m
    for m in available:
        if not is_heavy_ollama_model(m):
            return m
    return model or (available[0] if available else "")


def ollama_models() -> list[str]:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        ordered: list[str] = []
        used: set[str] = set()
        for pref in PREFERRED_MODELS:
            for m in models:
                if m not in used and _model_matches_installed(pref, m):
                    ordered.append(m)
                    used.add(m)
        rest = [m for m in models if m not in used]
        return ordered + rest
    except Exception:
        return []


def ollama_warmup(model: str) -> None:
    """모델을 미리 GPU에 올려 첫 응답 지연(콜드 스타트)을 줄입니다."""
    if not model or model == "(없음)":
        return
    try:
        requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
                "keep_alive": OLLAMA_KEEP_ALIVE,
                "options": {"num_predict": 1, "num_ctx": 512},
            },
            timeout=120,
        )
    except Exception:
        pass


from services.ollama_trace import (
    OllamaCallResult,
    consume_ollama_stream,
    empty_trace_step,
    iter_ollama_chat_stream,
    parse_ollama_json,
)
from services.chat_catalog import (
    build_chat_item,
    chat_fingerprint,
    dedupe_chat_items,
    is_live_autosave_file,
    prune_duplicate_chat_files,
    summarize_prompt_title,
)
from services.conversation_store import (
    autosave_session,
    markdown_to_messages,
    messages_to_markdown,
    new_live_chat_name,
    save_messages as save_messages_rich,
)
from ui.execution_trace import (
    merge_trace_metrics,
    model_wait_hint,
    render_busy_timer_fragment,
    render_execution_trace,
    render_live_progress,
    render_pipeline_tracker,
    render_message_with_trace,
    render_pending_excel_confirm,
    render_trace_metrics_footer,
    start_busy_timer,
    stop_busy_timer,
    tokens_dict_from_result,
)


def ollama_chat(
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
    options: dict[str, Any] | None = None,
) -> OllamaCallResult:
    opts = {**(options or OLLAMA_OPTS_CHAT), "temperature": temperature}
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": opts,
        **_ollama_payload_think(model),
    }
    t0 = time.perf_counter()
    timeout = 600 if is_heavy_ollama_model(model) else 300
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
    if r.status_code != 200:
        try:
            err_msg = r.json().get("error", r.text)
        except Exception:
            err_msg = r.text
        raise RuntimeError(f"Ollama 오류 ({r.status_code}): {err_msg}")
    wall = (time.perf_counter() - t0) * 1000
    return parse_ollama_json(r.json(), wall_elapsed_ms=wall, model=model)


def _likely_fast_builtin(prompt: str) -> bool:
    """차트/그래프 요청은 제외 — LLM 코드 생성 필요."""
    if _wants_chart(prompt):
        return False
    msg_lower = prompt.lower()
    if _wants_per_file_range(prompt) and not _asks_merge(msg_lower):
        return True
    return _wants_execution_rate_table(prompt)


def _wants_execution_rate_table(user_prompt: str) -> bool:
    """집행률 **표** 전용 — 그래프/차트는 LLM matplotlib 경로."""
    if _wants_chart(user_prompt):
        return False
    t = user_prompt.replace(" ", "")
    if "집행률" not in t and "집행률" not in user_prompt:
        return False
    graph_hints = ("그래프", "차트", "graph", "chart", "plot", "시각화", "그려")
    if any(h in t or h in user_prompt.lower() for h in graph_hints):
        return False
    return any(k in t for k in ("계획예산", "집행계", "집행", "예산"))


def _find_column(df: pd.DataFrame, candidates: tuple[str, ...], *, exclude: tuple[str, ...] = ()) -> str | None:
    cols = list(df.columns)
    for cand in candidates:
        for c in cols:
            if cand in str(c) and not any(ex in str(c) for ex in exclude):
                return str(c)
    return None


def _code_for_execution_rate_table(
    filenames: list[str],
    frames: dict[str, pd.DataFrame],
) -> str | None:
    """집행률 표용 pandas 코드 (승인 후 샌드박스 실행)."""
    blocks: list[str] = []
    for i, fname in enumerate(filenames):
        var = f"df_{i}"
        if var not in frames:
            continue
        df = frames[var]
        plan_col = _find_column(df, ("계획예산",))
        exec_col = _find_column(
            df,
            ("당해집행", "집행계", "집행액", "당해집행액", "합계"),
            exclude=("전년", "계획", "예산", "이월"),
        )
        if not plan_col or not exec_col:
            continue
        extra_cols = ""
        if "비목분류" in df.columns:
            extra_cols += f"_b['비목분류'] = _df['비목분류'].values\n    "
        if "비용명" in df.columns:
            extra_cols += f"_b['비용명'] = _df['비용명'].values\n    "
        blocks.append(textwrap.dedent(f"""\
        _df = {var}.copy()
        _p = pd.to_numeric(_df['{plan_col}'], errors='coerce')
        _e = pd.to_numeric(_df['{exec_col}'], errors='coerce')
        _b = pd.DataFrame({{
            '파일명': ['{fname}'] * len(_df),
            '{plan_col}': _p,
            '{exec_col}': _e,
        }})
        {extra_cols}_b['집행률(%)'] = (_e / _p * 100).where(_p > 0).round(2)
        parts.append(_b)
        """))
    if not blocks:
        return None
    return textwrap.dedent(f"""\
    import pandas as pd
    parts = []
    {''.join(blocks)}
    result = pd.concat(parts, ignore_index=True)
    result = result.sort_values('집행률(%)', ascending=False, na_position='last')
    """)


def _code_for_per_file_range(
    filenames: list[str],
    frames: dict[str, pd.DataFrame],
) -> str | None:
    """파일별 범위용 pandas 코드."""
    lines = ["import pandas as pd", "rows = []"]
    for i, fname in enumerate(filenames):
        var = f"df_{i}"
        if var not in frames:
            continue
        lines.append(textwrap.dedent(f"""\
        _df = {var}
        _filled = _df.map(lambda v: v is not None and str(v).strip() not in ('', 'nan', 'None', '-', '—'))
        _rm = _filled.any(axis=1)
        _cm = _filled.any(axis=0)
        _ri = [i for i, ok in enumerate(_rm) if ok]
        _ci = [i for i, ok in enumerate(_cm) if ok]
        rows.append({{
            '파일명': '{fname}',
            '시트_총행': len(_df),
            '시트_총열': len(_df.columns),
            '데이터_있는_행_수': len(_ri),
            '데이터_있는_열_수': len(_ci),
            '행_범위_1부터': f"{{_ri[0]+1}}~{{_ri[-1]+1}}" if _ri else '-',
            '열_범위_1부터': f"{{_ci[0]+1}}~{{_ci[-1]+1}}" if _ci else '-',
            '채워진_셀_수': int(_filled.sum().sum()),
        }})
        """))
    if len(lines) <= 2:
        return None
    lines.append("result = pd.DataFrame(rows)")
    return "\n".join(lines)


def try_builtin_execution_rate_table(
    user_prompt: str,
    filenames: list[str],
    frames: dict[str, pd.DataFrame],
) -> dict | None:
    """계획예산 대비 집행률(%) 표 — LLM 없이 즉시 계산."""
    if not _wants_execution_rate_table(user_prompt):
        return None
    parts: list[pd.DataFrame] = []
    for i, fname in enumerate(filenames):
        var = f"df_{i}"
        if var not in frames:
            continue
        df = frames[var].copy()
        plan_col = _find_column(df, ("계획예산",))
        exec_col = _find_column(
            df,
            ("당해집행", "집행계", "집행액", "당해집행액", "합계"),
            exclude=("전년", "계획", "예산", "이월"),
        )
        if not plan_col or not exec_col:
            continue
        plan = pd.to_numeric(df[plan_col], errors="coerce")
        spent = pd.to_numeric(df[exec_col], errors="coerce")
        rate = (spent / plan * 100).where(plan > 0)
        block: dict[str, Any] = {
            "파일명": fname,
            plan_col: plan,
            exec_col: spent,
            "집행률(%)": rate.round(2),
        }
        for extra in ("비목분류", "비용명"):
            if extra in df.columns:
                block[extra] = df[extra].values
        parts.append(pd.DataFrame(block))

    if not parts:
        return None

    result_df = pd.concat(parts, ignore_index=True)
    result_df = result_df.sort_values("집행률(%)", ascending=False, na_position="last")
    return {
        "dataframe": result_df,
        "preview": result_df.head(TABLE_PREVIEW_ROWS),
        "shape": {"rows": len(result_df), "cols": len(result_df.columns)},
        "explanation": (
            f"계획예산 대비 집행률(%)을 {len(filenames)}개 파일에서 계산했습니다 (내장 처리, LLM 생략)."
        ),
        "code": "# 내장: 계획예산 대비 집행률(%)",
    }


def _ensure_attached_files(attached: list[str]) -> list[str]:
    """첨부 목록이 비었으면 직전 세션 첨부를 복원."""
    if attached:
        st.session_state["_last_attached_files"] = list(attached)
        return attached
    prev = st.session_state.get("_last_attached_files") or []
    if prev:
        st.session_state.attached_files = list(prev)
        return list(prev)
    return attached


def ollama_generate_streamed(
    model: str,
    prompt: str,
    temperature: float = 0.2,
    options: dict[str, Any] | None = None,
) -> OllamaCallResult:
    """코드 생성 등 장시간 작업 — 스트리밍으로 진행 표시."""
    opts = {**(options or OLLAMA_OPTS_CODE), "temperature": temperature}
    t0 = time.perf_counter()
    think_lines: list[str] = []
    code_lines: list[str] = []
    think_box = st.expander("🧠 Thinking / 생성 중 (실시간)", expanded=True)
    code_box = st.empty()

    def on_token(role: str, text: str) -> None:
        if role == "thinking":
            think_lines.append(text)
            think_box.markdown("".join(think_lines)[-4000:] or "…")
        else:
            code_lines.append(text)
            code_box.code("".join(code_lines)[-12000:] or "# 생성 중…", language="python")

    chunks = iter_ollama_chat_stream(
        base_url=OLLAMA_URL,
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options=opts,
        keep_alive=OLLAMA_KEEP_ALIVE,
        timeout=600,
        think=_ollama_payload_think(model, force_no_think=True).get("think"),
    )
    wall = (time.perf_counter() - t0) * 1000
    return consume_ollama_stream(chunks, on_token=on_token, wall_elapsed_ms=wall, model=model)


def ollama_generate(
    model: str,
    prompt: str,
    temperature: float = 0.2,
    options: dict[str, Any] | None = None,
) -> OllamaCallResult:
    """단일 프롬프트를 /api/chat 으로 전송."""
    opts = {**(options or OLLAMA_OPTS_CODE), "temperature": temperature}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": opts,
        **_ollama_payload_think(model, force_no_think=True),
    }
    t0 = time.perf_counter()
    timeout = 600 if is_heavy_ollama_model(model) else 300
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
    if r.status_code != 200:
        try:
            err_msg = r.json().get("error", r.text)
        except Exception:
            err_msg = r.text
        raise RuntimeError(f"Ollama 오류 ({r.status_code}): {err_msg}")
    wall = (time.perf_counter() - t0) * 1000
    return parse_ollama_json(r.json(), wall_elapsed_ms=wall, model=model)


# ══════════════════════════════════════════════════════════════════════════════
# 페르소나 & 프롬프트 보강 (로컬 — 백엔드 불필요)
# ══════════════════════════════════════════════════════════════════════════════
from services.persona_prompt import build_enhanced_prompt, build_enhancement_meta
from services.persona_store import PersonaRecord, ensure_personas_file, get_persona, get_selected_persona
from ui.dashboard import (
    ROOT as PROJECT_ROOT,
    _cached_snapshot,
    render_dashboard_top,
    render_page_title,
    render_settings_section,
)
from ui.persona_ui import render_enhanced_prompt_preview, render_persona_sidebar
from ui.saved_chats import render_saved_chats_section
from ui.step_flow import init_step_flow_state, render_step_flow_sidebar, STEP_DEFS as FLOW_STEP_DEFS
from services.prompt_enhancer import _asks_merge, _asks_per_file, detect_intent, enhance as enhance_prompt

ensure_personas_file()


# ══════════════════════════════════════════════════════════════════════════════
# 엑셀 유틸리티
# ══════════════════════════════════════════════════════════════════════════════

def list_excel_files() -> list[dict]:
    files = []
    for p in sorted(EXCEL_DIR.iterdir()):
        if p.suffix.lower() in (".xlsx", ".xls", ".csv"):
            stat = p.stat()
            files.append({
                "name": p.name,
                "size": stat.st_size,
                "modified": datetime.datetime.fromtimestamp(stat.st_mtime),
                "path": str(p),
            })
    return files


def _deduplicate_columns(columns: list[str]) -> list[str]:
    """중복 컬럼명에 _2, _3 등 접미사를 붙여 고유하게 만든다."""
    seen: dict[str, int] = {}
    result = []
    for col in columns:
        if col in seen:
            seen[col] += 1
            result.append(f"{col}_{seen[col]}")
        else:
            seen[col] = 1
            result.append(col)
    return result


def read_excel_smart(path: str) -> pd.DataFrame:
    """다단 헤더 감지 및 병합 셀 처리를 포함한 엑셀 읽기."""
    p = Path(path)
    if p.suffix.lower() == ".csv":
        return pd.read_csv(path)

    df_raw = pd.read_excel(path, header=None)

    first_data_row = 0
    for i in range(min(5, len(df_raw))):
        row = df_raw.iloc[i]
        numeric_count = sum(1 for v in row if _is_numeric_like(v))
        if numeric_count >= len(row) * 0.4:
            first_data_row = i
            break

    if first_data_row >= 2:
        headers = []
        for col_idx in range(len(df_raw.columns)):
            parts = []
            for hrow in range(first_data_row):
                val = df_raw.iloc[hrow, col_idx]
                if pd.notna(val):
                    s = str(val).strip()
                    if s and s not in parts:
                        parts.append(s)
            headers.append("_".join(parts) if parts else f"col_{col_idx}")
        df = df_raw.iloc[first_data_row:].reset_index(drop=True)
        df.columns = _deduplicate_columns(headers)
    elif first_data_row == 1:
        df = pd.read_excel(path, header=0)
        df.columns = _deduplicate_columns([str(c) for c in df.columns])
    else:
        df = df_raw.copy()
        df.columns = [f"col_{i}" for i in range(len(df.columns))]

    for col in df.columns:
        df[col] = df[col].ffill()

    for col in df.select_dtypes(include=["object"]).columns:
        converted = df[col].apply(_try_numeric)
        if converted.notna().sum() > converted.isna().sum():
            df[col] = converted

    df.columns = _deduplicate_columns([str(c) for c in df.columns])
    return _coerce_numeric_columns(df)


def _is_numeric_like(v: Any) -> bool:
    if pd.isna(v):
        return False
    if isinstance(v, (int, float)):
        return True
    s = str(v).replace(",", "").strip()
    try:
        float(s)
        return True
    except ValueError:
        return False


def _try_numeric(v: Any) -> Any:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return v
    except (ValueError, TypeError):
        return v
    s = str(v).replace(",", "").strip()
    if not s or s in ("-", "—", "nan", "None"):
        return pd.NA
    try:
        return int(s) if "." not in s else float(s)
    except ValueError:
        return pd.NA


_TEXT_COL_KEYWORDS = ("비목", "비용명", "분류", "구분", "비고", "설명", "출처")


def _is_likely_text_column(col_name: str) -> bool:
    """숫자 변환에서 제외할 텍스트 성격 컬럼."""
    name = str(col_name)
    if name.startswith("col_"):
        return True
    return any(k in name for k in _TEXT_COL_KEYWORDS) and not any(
        k in name for k in ("예산", "집행", "금액", "합계", "잔액", "전년", "당년", "당해")
    )


def _coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """예산 표의 숫자 문자열(콤마 포함)을 float로 변환 — str/str 연산 오류 방지."""
    out = df.copy()
    for col in out.columns:
        if _is_likely_text_column(col):
            continue
        series = out[col]
        if pd.api.types.is_numeric_dtype(series):
            continue
        cleaned = (
            series.astype(str)
            .str.replace(",", "", regex=False)
            .str.strip()
            .replace({"": pd.NA, "-": pd.NA, "—": pd.NA, "nan": pd.NA, "None": pd.NA})
        )
        nums = pd.to_numeric(cleaned, errors="coerce")
        if nums.notna().sum() >= max(2, int(len(out) * 0.15)):
            out[col] = nums
    return out


def file_size_fmt(size: int) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _cell_has_value(v: Any) -> bool:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return False
    s = str(v).strip()
    return bool(s) and s.lower() not in ("nan", "none", "-", "—")


def compute_filled_range_stats(df: pd.DataFrame, filename: str) -> dict[str, Any]:
    """시트에서 값이 들어 있는 행·열 범위와 셀 개수."""
    filled = df.map(_cell_has_value)
    if not filled.any().any():
        return {
            "파일명": filename,
            "시트_총행": len(df),
            "시트_총열": len(df.columns),
            "데이터_있는_행_수": 0,
            "데이터_있는_열_수": 0,
            "행_범위_1부터": "-",
            "열_범위_1부터": "-",
            "채워진_셀_수": 0,
        }
    row_mask = filled.any(axis=1)
    col_mask = filled.any(axis=0)
    row_idx = [i for i, ok in enumerate(row_mask) if ok]
    col_idx = [i for i, ok in enumerate(col_mask) if ok]
    return {
        "파일명": filename,
        "시트_총행": len(df),
        "시트_총열": len(df.columns),
        "데이터_있는_행_수": len(row_idx),
        "데이터_있는_열_수": len(col_idx),
        "행_범위_1부터": f"{row_idx[0] + 1}~{row_idx[-1] + 1}",
        "열_범위_1부터": f"{col_idx[0] + 1}~{col_idx[-1] + 1}",
        "채워진_셀_수": int(filled.sum().sum()),
    }


def _wants_chart(user_prompt: str) -> bool:
    m = user_prompt.lower()
    return any(k in m for k in ("차트", "그래프", "chart", "graph", "plot", "시각화", "그려"))


def _wants_per_file_range(user_prompt: str) -> bool:
    m = user_prompt.lower()
    range_hints = ("범위", "라인", "line", "컬럼", "column", "행", "열", "입력", "채워", "갯수", "개수")
    if _asks_per_file(m, user_prompt) and any(h in m for h in range_hints):
        return True
    return detect_intent(user_prompt) == "FILE_META"


def try_builtin_per_file_range(
    user_prompt: str,
    filenames: list[str],
    frames: dict[str, pd.DataFrame],
) -> dict | None:
    """파일별 입력 범위 질문은 LLM 없이 정확히 계산."""
    if not _wants_per_file_range(user_prompt) or _asks_merge(user_prompt.lower()):
        return None
    rows: list[dict[str, Any]] = []
    for i, fname in enumerate(filenames):
        var = f"df_{i}"
        if var not in frames:
            continue
        rows.append(compute_filled_range_stats(frames[var], fname))
    if not rows:
        return None
    result_df = pd.DataFrame(rows)
    shape = {"rows": len(result_df), "cols": len(result_df.columns)}
    return {
        "dataframe": result_df,
        "preview": result_df.head(TABLE_PREVIEW_ROWS),
        "shape": shape,
        "explanation": "파일별로 입력된 행·열 범위를 계산했습니다 (데이터 병합 없음).",
        "code": "# 내장: 파일별 입력 범위 (LLM 생략)",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 코드 샌드박스 실행
# ══════════════════════════════════════════════════════════════════════════════

FORBIDDEN_MODULES = {
    "os", "sys", "subprocess", "shutil", "pathlib",
    "importlib", "socket", "http", "urllib", "requests",
    "ctypes", "pickle", "shelve", "signal",
}
ALLOWED_MODULES = {"pandas", "numpy", "matplotlib", "json", "math", "re", "collections"}


def _validate_code(code: str) -> str | None:
    """AST 기반 정적 분석으로 위험 코드 차단. 문제 시 오류 메시지 반환."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"구문 오류: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod in FORBIDDEN_MODULES:
                    return f"금지된 모듈: {mod}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod = node.module.split(".")[0]
                if mod in FORBIDDEN_MODULES:
                    return f"금지된 모듈: {mod}"
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in ("eval", "exec", "compile", "__import__"):
                return f"금지된 함수: {func.id}"
            if isinstance(func, ast.Attribute) and func.attr in ("system", "popen", "remove", "rmdir", "unlink"):
                return f"금지된 메서드: {func.attr}"
    return None


def execute_pandas_code(code: str, dataframes: dict[str, pd.DataFrame]) -> dict:
    """샌드박스에서 pandas 코드를 실행하고 결과를 반환."""
    err = _validate_code(code)
    if err:
        return {"error": err}

    with tempfile.TemporaryDirectory() as tmpdir:
        for name, df in dataframes.items():
            df.to_pickle(os.path.join(tmpdir, f"{name}.pkl"))

        _project_root = str(Path(__file__).resolve().parent)
        runner = textwrap.dedent(f"""\
        import sys
        sys.path.insert(0, {_project_root!r})
        import pandas as pd
        import numpy as np
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import json, os, pickle

        from services.korean_matplotlib import setup_korean_matplotlib
        _chart_font = setup_korean_matplotlib()

        tmpdir = {tmpdir!r}
        chart_path = os.path.join(tmpdir, '__chart__.png')
        os.chdir(tmpdir)

        frames = {{}}
        for f in os.listdir(tmpdir):
            if f.endswith('.pkl') and not f.startswith('__'):
                frames[f[:-4]] = pd.read_pickle(os.path.join(tmpdir, f))

        for _name, _df in frames.items():
            globals()[_name] = _df
            globals()[f"{{_name}}_COLUMNS"] = list(_df.columns)

        # ── 사용자 코드 ──
        {textwrap.indent(code, '        ').strip()}
        # ── 끝 ──

        # savefig 미호출 시 열린 figure 자동 저장 (AI가 Malgun 등으로 덮어쓴 경우 재설정)
        if plt.get_fignums():
            setup_korean_matplotlib()
            if not os.path.exists(chart_path):
                plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            plt.close('all')
        elif os.path.exists('__chart__.png') and not os.path.exists(chart_path):
            os.rename('__chart__.png', chart_path)

        if 'result' in dir():
            r = result
        else:
            r = None
            for v in list(locals().values()):
                if isinstance(v, pd.DataFrame):
                    r = v

        if r is not None and isinstance(r, pd.DataFrame):
            r.to_pickle(os.path.join(tmpdir, '__result__.pkl'))
            info = {{"rows": len(r), "cols": len(r.columns)}}
            with open(os.path.join(tmpdir, '__info__.json'), 'w') as fp:
                json.dump(info, fp)
        elif r is not None:
            with open(os.path.join(tmpdir, '__scalar__.txt'), 'w') as fp:
                fp.write(str(r))
        """)

        runner_path = os.path.join(tmpdir, "__runner__.py")
        with open(runner_path, "w") as f:
            f.write(runner)

        try:
            proc = subprocess.run(
                [sys.executable, runner_path],
                capture_output=True, text=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            return {"error": "실행 시간 초과 (60초)"}

        if proc.returncode != 0:
            return {"error": proc.stderr.strip() or "실행 실패"}

        result_pkl = os.path.join(tmpdir, "__result__.pkl")
        scalar_txt = os.path.join(tmpdir, "__scalar__.txt")
        info_json = os.path.join(tmpdir, "__info__.json")
        chart_png = os.path.join(tmpdir, "__chart__.png")

        out: dict[str, Any] = {}

        if os.path.exists(chart_png):
            with open(chart_png, "rb") as fp:
                out["chart_bytes"] = fp.read()

        if os.path.exists(result_pkl):
            import json
            result_df = pd.read_pickle(result_pkl)
            with open(info_json) as fp:
                info = json.load(fp)
            out.update({
                "dataframe": result_df,
                "shape": info,
                "preview": result_df.head(TABLE_PREVIEW_ROWS),
            })
            return out
        elif os.path.exists(scalar_txt):
            with open(scalar_txt) as fp:
                out["scalar"] = fp.read().strip()
            return out
        elif out.get("chart_bytes"):
            return out
        else:
            stdout = proc.stdout.strip()
            return {"stdout": stdout} if stdout else {"error": "결과가 생성되지 않았습니다."}


# ══════════════════════════════════════════════════════════════════════════════
# AI 엑셀 처리 파이프라인
# ══════════════════════════════════════════════════════════════════════════════

def build_data_context(filenames: list[str]) -> tuple[str, dict[str, pd.DataFrame]]:
    """첨부 파일들을 읽어서 AI 컨텍스트 문자열과 DataFrame dict를 반환."""
    frames: dict[str, pd.DataFrame] = {}
    context_parts: list[str] = []

    for i, fname in enumerate(filenames):
        path = EXCEL_DIR / fname
        if not path.exists():
            continue
        df = read_excel_smart(str(path))
        var_name = f"df_{i}"
        frames[var_name] = df
        null_pct = (df.isna().sum() / max(len(df), 1) * 100).round(1)
        null_top = null_pct[null_pct > 0].sort_values(ascending=False).head(6)
        null_lines = ", ".join(f"{k}:{v}%" for k, v in null_top.items()) or "없음"
        context_parts.append(
            f"### {var_name} = '{fname}'\n"
            f"- Shape: {df.shape[0]}행 × {df.shape[1]}열\n"
            f"- Columns: {list(df.columns)}\n"
            f"- dtypes: {dict(df.dtypes.astype(str))}\n"
            f"- 결측 비율(상위): {null_lines}\n"
        )

    return "\n".join(context_parts), frames


def _columns_reference_block(
    frames: dict[str, pd.DataFrame],
    *,
    allow_merge: bool = True,
) -> str:
    """AI가 컬럼명을 오타내지 않도록 repr 문자열 목록 제공."""
    lines = ["## 사용 가능한 컬럼명 (아래 문자열을 그대로 복사 — 한자 算/산 혼동 금지)"]
    for var_name, df in frames.items():
        cols_repr = ", ".join(repr(c) for c in df.columns)
        lines.append(f"- {var_name}: {cols_repr}")
    lines.append("- 예: `df['계획예산']` (O) / `df['계획예算']` (X — KeyError)")
    if allow_merge:
        lines.append(
            "- 여러 파일 통합(사용자가 병합 요청한 경우만): "
            "`pd.concat([df_0.assign(출처='파일1'), df_1.assign(출처='파일2'), ...])`"
        )
    else:
        lines.append("- **이 요청에서는 pd.concat / merge / join 금지** — df_0, df_1을 각각 따로 처리.")
    return "\n".join(lines)


def generate_code_prompt(
    user_prompt: str,
    data_context: str,
    frame_names: list[str],
    frames: dict[str, pd.DataFrame] | None = None,
    prev_error: str | None = None,
    *,
    per_file_mode: bool = False,
    allow_merge: bool = True,
    allow_chart: bool = False,
) -> str:
    error_section = ""
    if prev_error:
        error_section = textwrap.dedent(f"""\
        ## 이전 시도에서 발생한 오류
        아래 오류를 반드시 수정하세요:
        ```
        {prev_error}
        ```
        """)

    per_file_section = ""
    if per_file_mode:
        per_file_section = textwrap.dedent("""\
        ## ★ 파일별 작업 (필수)
        - 사용자는 **각 파일을 따로** 분석하라고 했습니다.
        - `pd.concat`, `merge`, `join`으로 데이터 행을 합치지 마세요.
        - 집행률·차트 등 **요청에 없는** 계산·시각화를 하지 마세요.
        - `result`는 파일당 1행(또는 파일별 요약)인 표로 만드세요. `파일명` 열을 포함하세요.
        - 예: df_0, df_1 각각에 대해 행·열 범위·채워진 셀 수를 구한 뒤 `pd.DataFrame([...])` 로 합침.
        """)

    chart_section = ""
    if allow_chart:
        chart_section = textwrap.dedent("""\
        ## 시각화 규칙
        - 차트가 필요하면 `import matplotlib.pyplot as plt` 사용
        - 한글 폰트는 샌드박스가 자동 설정합니다. `plt.rcParams['font.family']` 를 **직접 바꾸지 마세요**
        - 차트: `plt.figure(figsize=(10,6))` → `plt.bar(...)` 등 → `plt.savefig('__chart__.png', dpi=150, bbox_inches='tight')` → `plt.close()`
        - 작업 디렉터리가 임시 폴더이므로 파일명 `__chart__.png` 만 사용
        - 차트와 데이터 결과를 **둘 다** 생성하세요 (result 변수 필수)
        - **차트 그리기 전** 반드시 `plot_df = result.dropna(subset=['집행률']).copy()` 처럼
          **행 단위로** 결측을 제거한 뒤, `plot_df['x컬럼']`과 `plot_df['y컬럼']`을 함께 사용하세요.
        - `plt.bar(result['A'], result['B'].dropna())` 는 **금지** (x·y 길이 불일치).
        - 막대가 너무 많으면 상위 10~15개만: `plot_df = result.nlargest(15, '집행률')`
        - x축 라벨이 길면 `plt.xticks(rotation=45, ha='right')` 사용
        """)
    else:
        chart_section = "## 시각화\n- 사용자가 차트를 요청하지 않았습니다. **matplotlib/plt 코드를 작성하지 마세요.**\n"

    return textwrap.dedent(f"""\
    당신은 pandas/numpy/matplotlib 전문가입니다. 사용자의 요청을 수행하는 Python 코드를 생성하세요.

    ## 필수 규칙
    1. pandas, numpy, matplotlib만 사용 가능합니다.
    2. 결과를 `result` 변수에 DataFrame으로 저장하세요.
    3. 사용 가능한 DataFrame 변수: {', '.join(frame_names)} — **이미 메모리에 로드됨**
    4. `pd.read_excel()`, `pd.read_csv()` 로 파일을 읽지 마세요 (FileNotFoundError).
       반드시 `df = df_0.copy()` 처럼 위 변수만 사용하세요.
    5. 코드만 출력하세요 — 설명이나 마크다운 없이 순수 Python 코드만.
    6. print() 사용 금지. 결과는 반드시 result 변수에 할당.
    7. 컬럼명은 아래 「사용 가능한 컬럼명」에 있는 **repr 문자열을 복사**해 사용하세요.
       유사 한자·추측 금지 (예: 계획예산 ≠ 계획예算).
    8. 산술 연산 전에 숫자 컬럼은 반드시
       `pd.to_numeric(df['컬럼명'], errors='coerce')` 로 변환하세요.
    9. 나눗셈 시 분모가 0이면 `pd.NA` 처리 (0으로 나누기 금지).

    ## ★ 컬럼 참조 규칙 (매우 중요)
    - **데이터 정보에 나열된 컬럼만 사용하세요.**
    - 새 컬럼을 만든 후, **다음 줄부터** 참조하세요. 같은 줄에서 참조 금지.
    - 예시 (올바른 코드):
      ```
      df['집행률'] = pd.to_numeric(df['당해집행'], errors='coerce') / pd.to_numeric(df['계획예산'], errors='coerce') * 100
      result = df.sort_values('집행률', ascending=False)
      ```
    - 예시 (잘못된 코드 — KeyError 발생):
      ```
      result = df.assign(집행률=...).merge(df[['집행률']])  # '집행률'은 아직 df에 없음!
      ```

    {per_file_section}
    {chart_section}

    {error_section}
    ## 데이터 정보
    {data_context}

    {_columns_reference_block(frames, allow_merge=allow_merge) if frames else ""}

    ## 사용자 요청
    {user_prompt}

    ## Python 코드 (result 변수에 결과 저장):
    """)


def extract_code_block(text: str, *, fallback: str = "") -> str:
    """AI 응답에서 Python 코드 블록을 추출 (Gemma4 thinking 폴백 포함)."""
    for source in (text, fallback):
        if not source or not source.strip():
            continue
        patterns = [
            r"```python\s*\n(.*?)```",
            r"```\s*\n(.*?)```",
        ]
        for pat in patterns:
            m = re.search(pat, source, re.DOTALL)
            if m:
                return m.group(1).strip()

        lines = source.strip().split("\n")
        code_lines = [
            l for l in lines
            if not l.startswith("#") or "import" in l or "=" in l
        ]
        joined = "\n".join(code_lines).strip()
        if joined and ("import " in joined or "result" in joined or "pd." in joined):
            return joined
    return ""


def _sanitize_llm_excel_reads(code: str, filenames: list[str]) -> tuple[str, bool]:
    """
    LLM이 pd.read_excel/read_csv를 다시 호출한 코드를 메모리 DataFrame 참조로 교체.

    샌드박스에는 원본 파일이 없고 df_0, df_1...만 주입되므로
    FileNotFoundError를 방지하기 위해 안전한 형태로 보정합니다.
    """
    replaced = False
    out = code
    for i, fname in enumerate(filenames):
        alias = f"df_{i}"
        # df_x = pd.read_excel('file.xlsx') / "file.xlsx" 패턴
        assign_pat = re.compile(
            rf"^\s*([A-Za-z_]\w*)\s*=\s*pd\.(read_excel|read_csv)\(\s*['\"]{re.escape(fname)}['\"].*?\)\s*$",
            re.MULTILINE,
        )

        def _assign_sub(m: re.Match[str]) -> str:
            nonlocal replaced
            replaced = True
            lhs = m.group(1)
            return f"{lhs} = {alias}.copy()"

        out = assign_pat.sub(_assign_sub, out)

        # 단독 호출 pd.read_excel('file.xlsx') 도 치환
        call_pat = re.compile(
            rf"pd\.(read_excel|read_csv)\(\s*['\"]{re.escape(fname)}['\"].*?\)"
        )
        if call_pat.search(out):
            replaced = True
            out = call_pat.sub(f"{alias}.copy()", out)

    # 여전히 read_excel/read_csv가 남아있으면 주석으로 경고 라인 추가
    if re.search(r"pd\.(read_excel|read_csv)\(", out):
        replaced = True
        out = (
            "# NOTE: 파일 재읽기 코드는 샌드박스에서 실패하므로 df_0, df_1...을 사용해야 합니다.\n"
            + out
        )
    return out, replaced


def _excel_codegen_flags(user_prompt: str) -> dict[str, bool]:
    msg_lower = user_prompt.lower()
    allow_merge = _asks_merge(msg_lower)
    per_file_mode = (
        _asks_per_file(msg_lower, user_prompt) and not allow_merge
    ) or detect_intent(user_prompt) == "FILE_META"
    return {
        "allow_merge": allow_merge,
        "per_file_mode": per_file_mode,
        "allow_chart": _wants_chart(user_prompt),
    }


def generate_excel_code_only(
    user_prompt: str,
    filenames: list[str],
    model: str,
    *,
    thinking_steps: list[dict[str, str]] | None = None,
    max_retries: int = 2,
    on_progress: Callable[[str], None] | None = None,
    use_stream: bool = True,
    persona_plan: Any | None = None,
    preloaded_frames: dict[str, pd.DataFrame] | None = None,
    preloaded_data_context: str | None = None,
) -> dict[str, Any]:
    """코드만 생성 (실행 전). builtin·Persona 도구 경로 포함."""
    from src.prompt_builder import build_code_generation_prompt

    steps = list(thinking_steps or [])
    if preloaded_frames is not None:
        frames = preloaded_frames
        data_context = preloaded_data_context or ""
    else:
        if on_progress:
            on_progress("📂 첨부 Excel 파일 읽는 중…")
        data_context, frames = build_data_context(filenames)
    if not frames:
        return {"error": "첨부된 파일을 읽을 수 없습니다.", "thinking_steps": steps}

    if persona_plan and getattr(persona_plan, "tool_formatted_markdown", None):
        if persona_plan.execution_path == "tool_response":
            steps.extend(persona_plan.thinking_steps)
            steps.append(empty_trace_step("응답 생성", "Persona 도구 결과 → 템플릿 출력 (LLM 생략)"))
            return {
                "direct_content": persona_plan.tool_formatted_markdown,
                "frames": frames,
                "filenames": filenames,
                "thinking_steps": steps,
                "ollama_calls": [],
                "code_source": "persona_tools",
            }

    steps.append(empty_trace_step("데이터 로드", f"{len(frames)}개 DataFrame · 컨텍스트 생성"))
    if on_progress:
        on_progress(f"✅ {len(frames)}개 파일 로드 완료")
    msg_lower = user_prompt.lower()
    template_code: str | None = None
    if _wants_per_file_range(user_prompt) and not _asks_merge(msg_lower):
        template_code = _code_for_per_file_range(filenames, frames)
        if template_code:
            steps.append(empty_trace_step("코드 준비", "파일별 범위 — 템플릿 pandas (승인 후 실행)"))
    elif _wants_execution_rate_table(user_prompt):
        template_code = _code_for_execution_rate_table(filenames, frames)
        if template_code:
            steps.append(empty_trace_step("코드 준비", "집행률(%) 표 — 템플릿 pandas (승인 후 실행)"))
    if template_code:
        steps.append(empty_trace_step("실행 대기", "사용자 승인 후 샌드박스 실행"))
        return {
            "code": template_code,
            "frames": frames,
            "filenames": filenames,
            "thinking_steps": steps,
            "ollama_calls": [],
            "code_source": "template",
        }

    flags = _excel_codegen_flags(user_prompt)
    steps.append(empty_trace_step(
        "규칙 적용",
        f"merge={flags['allow_merge']} · per_file={flags['per_file_mode']} · chart={flags['allow_chart']}",
    ))

    prev_error: str | None = None
    last_code = ""
    ollama_calls: list[OllamaCallResult] = []
    attempts = max_retries + 1 if len(frames) <= 2 else 2
    exec_result: dict[str, Any] = {}

    for attempt in range(attempts):
        steps.append(empty_trace_step("코드 생성 LLM", f"시도 {attempt + 1}/{attempts}"))
        if persona_plan and getattr(persona_plan, "profile", None):
            code_prompt = build_code_generation_prompt(
                persona_plan.profile,
                user_prompt,
                data_context,
                intent=persona_plan.strategy.intent,
                tool_context=persona_plan.tool_results,
                flags=flags,
                prev_error=prev_error,
            )
        else:
            code_prompt = generate_code_prompt(
                user_prompt,
                data_context,
                list(frames.keys()),
                frames=frames,
                prev_error=prev_error,
                per_file_mode=flags["per_file_mode"],
                allow_merge=flags["allow_merge"],
                allow_chart=flags["allow_chart"],
            )
        try:
            if on_progress:
                on_progress(f"🤖 코드 생성 LLM ({model}) — 시도 {attempt + 1}/{attempts}")
            # 스트리밍은 일부 환경에서 멈춤 — 기본은 비스트리밍(안정)
            gen = ollama_generate(
                model, code_prompt, temperature=0.1, options=OLLAMA_OPTS_CODE,
            )
            ollama_calls.append(gen)
            if on_progress:
                on_progress(f"✅ 코드 수신 ({gen.elapsed_ms:.0f}ms)")
        except Exception as e:
            hint = ""
            err = str(e).lower()
            if "memory" in err or "system memory" in err:
                hint = " 사이드바에서 **qwen2.5:7b** 등 작은 모델을 선택하세요."
            return {"error": f"AI 코드 생성 실패: {e}{hint}", "thinking_steps": steps}

        code = extract_code_block(gen.content, fallback=gen.thinking)
        if not code:
            return {
                "error": "AI가 유효한 코드를 생성하지 못했습니다.",
                "raw": gen.content,
                "thinking_steps": steps,
                "ollama_calls": ollama_calls,
            }
        code, sanitized = _sanitize_llm_excel_reads(code, filenames)
        if sanitized:
            steps.append(empty_trace_step("코드 보정", "pd.read_excel/read_csv → 메모리 df 참조로 변환"))
        last_code = code
        steps.append(empty_trace_step("코드 추출", f"{len(code.splitlines())}줄"))
        steps.append(empty_trace_step("실행 대기", "사용자 승인 후 샌드박스 실행"))
        if attempt == 0:
            return {
                "code": code,
                "frames": frames,
                "filenames": filenames,
                "flags": flags,
                "data_context": data_context,
                "thinking_steps": steps,
                "ollama_calls": ollama_calls,
                "gen_thinking": gen.thinking,
                "code_source": "llm",
            }
        exec_result = execute_pandas_code(code, frames)
        if "error" not in exec_result:
            break
        prev_error = f"코드:\n{code}\n\n오류:\n{exec_result['error']}"
        steps.append(empty_trace_step("실행 실패", exec_result["error"][:200]))

    return {**exec_result, "code": last_code, "thinking_steps": steps, "ollama_calls": ollama_calls}


def execute_prepared_excel_code(
    code: str,
    frames: dict[str, pd.DataFrame],
    user_prompt: str,
    model: str,
    *,
    thinking_steps: list[dict[str, str]] | None = None,
    ollama_calls: list[OllamaCallResult] | None = None,
) -> dict[str, Any]:
    """확인 후 샌드박스 실행 + 설명."""
    steps = list(thinking_steps or [])
    steps.append(empty_trace_step("AST 검증", "위험 모듈·eval 차단"))
    t0 = time.perf_counter()
    exec_result = execute_pandas_code(code, frames)
    sandbox_ms = (time.perf_counter() - t0) * 1000
    steps.append(empty_trace_step(
        "샌드박스 실행",
        "성공" if "error" not in exec_result else exec_result.get("error", "")[:120],
    ))

    if "error" in exec_result:
        return {**exec_result, "code": code, "thinking_steps": steps, "sandbox_ms": sandbox_ms}

    explanation = ""
    explain_call: OllamaCallResult | None = None
    if not st.session_state.get("fast_mode", True):
        try:
            explain_prompt = (
                f"다음 pandas 실행 결과를 한국어 3문장으로 요약하세요.\n"
                f"결과 shape: {exec_result.get('shape', exec_result.get('scalar', 'N/A'))}\n"
            )
            explain_call = ollama_generate(
                model, explain_prompt, temperature=0.3, options=OLLAMA_OPTS_EXPLAIN,
            )
            explanation = explain_call.content
            steps.append(empty_trace_step("결과 설명 LLM", explain_call.usage_summary()))
        except Exception:
            explanation = "설명 생성을 건너뛰었습니다."
    elif "shape" in exec_result:
        explanation = (
            f"표 결과 {exec_result['shape']['rows']}행 × "
            f"{exec_result['shape']['cols']}열 (빠른 모드: LLM 설명 생략)"
        )

    calls = list(ollama_calls or [])
    if explain_call:
        calls.append(explain_call)
    return {
        **exec_result,
        "code": code,
        "explanation": explanation,
        "thinking_steps": steps,
        "ollama_calls": calls,
        "sandbox_ms": sandbox_ms,
    }


def process_excel_prompt(
    user_prompt: str,
    filenames: list[str],
    model: str,
    max_retries: int = 2,
) -> dict:
    """레거시 일괄 처리 (확인 없이)."""
    gen = generate_excel_code_only(user_prompt, filenames, model, max_retries=max_retries)
    if gen.get("error"):
        return gen
    return execute_prepared_excel_code(
        gen["code"],
        gen["frames"],
        user_prompt,
        model,
        thinking_steps=gen.get("thinking_steps"),
        ollama_calls=gen.get("ollama_calls"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 결과 내보내기
# ══════════════════════════════════════════════════════════════════════════════

def save_result_excel(df: pd.DataFrame, name: str) -> Path:
    path = RESULTS_DIR / f"{name}.xlsx"
    df.to_excel(path, index=False, engine="openpyxl")
    return path


def _ensure_chat_session() -> str:
    if not st.session_state.get("chat_session_id"):
        st.session_state.chat_session_id = str(uuid.uuid4())
    if not st.session_state.get("active_chat_file"):
        st.session_state.active_chat_file = new_live_chat_name(st.session_state.chat_session_id)
    return st.session_state.active_chat_file


def _chat_summary_title(messages: list[dict]) -> str:
    from services.chat_catalog import first_user_prompt_from_messages

    prompt = first_user_prompt_from_messages(messages)
    return summarize_prompt_title(prompt)


def _autosave_messages(messages: list[dict]) -> Path | None:
    if not messages:
        return None
    live = _ensure_chat_session()
    title = _chat_summary_title(messages)
    path = save_messages_rich(
        messages,
        live,
        results_dir=RESULTS_DIR,
        summary_title=title,
    )
    st.session_state["_last_saved_chat"] = str(path)
    return path


def _find_snapshot_for_fingerprint(fp: str) -> Path | None:
    """동일 주제의 기존 스냅샷 (chat_*.md, live 제외)."""
    if not fp:
        return None
    for item in list_saved_chats(limit=80, dedupe=False):
        if is_live_autosave_file(item["name"]):
            continue
        if item.get("fingerprint") == fp:
            return Path(item["path"])
    return None


def save_conversation_md(messages: list[dict], name: str) -> Path:
    """수동 저장 — trace 포함 MD. 동일 주제면 기존 파일 갱신."""
    title = _chat_summary_title(messages)
    fp = chat_fingerprint(messages)
    existing = _find_snapshot_for_fingerprint(fp)
    if existing and not is_live_autosave_file(existing.name):
        return save_messages_rich(
            messages,
            existing.name,
            results_dir=RESULTS_DIR,
            summary_title=title,
        )
    if not name.endswith(".md"):
        name = f"{name}.md"
    return save_messages_rich(
        messages,
        name,
        results_dir=RESULTS_DIR,
        summary_title=title,
    )


def list_saved_chats(limit: int = 30, *, dedupe: bool = True) -> list[dict]:
    """results/ 아래 저장 대화 (live 자동저장 파일 제외, 중복 제거)."""
    items: list[dict] = []
    for p in RESULTS_DIR.glob("chat_*.md"):
        row = build_chat_item(p, load_messages_fn=load_conversation_md)
        if row:
            items.append(row)
    if dedupe and items:
        prune_duplicate_chat_files(items, results_dir=RESULTS_DIR)
        items = dedupe_chat_items(items)
    return items[:limit]


def load_conversation_md(path: Path) -> list[dict]:
    """저장된 .md 대화를 messages 형식으로 복원 (trace 포함)."""
    return markdown_to_messages(path.read_text(encoding="utf-8"))


def dataframe_to_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# Step Flow — Step별 개별 실행
# ══════════════════════════════════════════════════════════════════════════════

def handle_flow_execution() -> bool:
    """Step Flow 실행 요청 처리 — 한 번에 한 Step만 실행."""
    if not st.session_state.pop("_flow_execute_requested", False):
        return False

    from services.step_flow_engine import (
        build_data_flow_summary,
        get_step_prompt_with_context,
        prepare_flow_execution,
    )

    flow_sel = dict(st.session_state.get("step_flow", {}))
    flow_result = prepare_flow_execution(
        flow_sel,
        list(FLOW_STEP_DEFS),
        results_dir=RESULTS_DIR,
    )

    if flow_result.status == "no_valid_steps":
        st.warning("유효한 Step이 없습니다. 저장된 대화를 선택해 주세요.")
        return True

    valid_steps = [s for s in flow_result.steps if s.is_valid()]
    if not valid_steps:
        st.warning("선택된 대화에서 유효한 내용을 추출할 수 없습니다.")
        return True

    # Flow 상태 초기화 또는 이어서 실행
    current_idx = st.session_state.get("_flow_current_step_idx", 0)

    if current_idx >= len(valid_steps):
        # 모든 Step 완료 — 최종 요약
        data_flow_md = build_data_flow_summary(valid_steps)
        step_summary = " → ".join(f"**{s.step_label}**" for s in valid_steps)
        st.session_state.messages.append({
            "role": "assistant",
            "content": (
                f"✅ **Step Flow 전체 완료**\n\n"
                f"실행 경로: {step_summary}\n\n"
                f"{data_flow_md}"
            ),
            "trace": {"status": "flow_completed", "flow_steps": len(valid_steps)},
        })
        # Flow 상태 정리
        st.session_state.pop("_flow_current_step_idx", None)
        st.session_state.pop("_flow_valid_steps_cache", None)
        st.session_state.pop("flow_running_step", None)
        st.session_state["_flow_last_result"] = {
            "steps": [{"step_label": s.step_label, "status": "completed"} for s in valid_steps],
            "data_flow_md": data_flow_md,
        }
        return True

    # 현재 Step 실행
    step_ctx = valid_steps[current_idx]
    st.session_state["flow_running_step"] = step_ctx.step_id

    # 이전 Step 컨텍스트 포함 프롬프트 생성
    enhanced_prompt = get_step_prompt_with_context(
        current_idx,
        valid_steps,
    )

    if not enhanced_prompt:
        st.session_state["_flow_current_step_idx"] = current_idx + 1
        st.session_state["_flow_execute_requested"] = True
        return True

    # Flow 시작 안내 (첫 Step일 때만)
    if current_idx == 0:
        st.session_state.messages.append({
            "role": "assistant",
            "content": (
                f"🔗 **Step Flow 시작** — {len(valid_steps)}개 Step을 순서대로 실행합니다.\n\n"
                f"각 Step 완료 후 사이드바에서 **▶ 다음 Step**을 눌러 이어갈 수 있습니다."
            ),
            "trace": {"status": "flow_start", "flow_steps": len(valid_steps)},
        })

    # 컨텍스트 정보 표시
    context_note = ""
    if current_idx > 0:
        prev_labels = [s.step_label for s in valid_steps[:current_idx]]
        context_note = f"\n\n> 📎 이전 단계 반영: {', '.join(prev_labels)}"

    # 유효한 Step 캐시 저장 (다음 Step 실행 시 재사용)
    import dataclasses
    st.session_state["_flow_valid_steps_cache"] = [
        dataclasses.asdict(s) for s in valid_steps
    ]
    st.session_state["_flow_current_step_idx"] = current_idx + 1

    # pending_prompt에 프롬프트를 넣어서 일반 채팅 파이프라인으로 실행
    flow_header = f"**[{step_ctx.step_label} · Flow]** "
    st.session_state.pending_prompt = enhanced_prompt
    st.session_state["_flow_step_header"] = (
        f"{flow_header}{step_ctx.user_prompt[:120]}{context_note}"
    )

    return True


def _inject_flow_step_header() -> None:
    """Flow Step 실행 시 채팅에 Step 헤더를 표시합니다."""
    header = st.session_state.pop("_flow_step_header", "")
    if header:
        st.session_state.messages.append({
            "role": "assistant",
            "content": header,
            "trace": {
                "status": "flow_step_header",
                "flow_step": st.session_state.get("flow_running_step", ""),
            },
        })


# ══════════════════════════════════════════════════════════════════════════════
# 메시지 포맷팅
# ══════════════════════════════════════════════════════════════════════════════

def format_result(result: dict) -> str:
    parts: list[str] = []

    if result.get("error"):
        parts.append(f"❌ **오류**\n```\n{result['error']}\n```")
        if result.get("raw"):
            parts.append(f"\n<details><summary>AI 원본 응답</summary>\n\n```\n{result['raw']}\n```\n</details>")

    if result.get("shape"):
        parts.append(f"✅ 처리 완료 — **{result['shape']['rows']}행 × {result['shape']['cols']}열**\n")

    if result.get("preview") is not None or result.get("dataframe") is not None:
        total = result.get("shape", {}).get("rows", "?")
        parts.append(
            f"📋 결과 표는 아래에 **상위 {TABLE_PREVIEW_ROWS}행**만 표시합니다 "
            f"(전체 {total}행 · 전체는 사이드바 **📥 Excel**)."
        )

    if result.get("scalar"):
        parts.append(f"📊 결과: **{result['scalar']}**")

    if result.get("chart_bytes"):
        parts.append("\n📈 **차트가 생성되었습니다** (아래 표시)")

    if result.get("stdout"):
        parts.append(f"```\n{result['stdout']}\n```")

    if result.get("explanation"):
        parts.append(f"\n📝 {result['explanation']}")

    if result.get("code"):
        parts.append(
            f"\n<details><summary>생성된 코드 보기</summary>\n\n"
            f"```python\n{result['code']}\n```\n</details>"
        )

    return "\n".join(parts) or "결과가 없습니다."


def render_result_table(result: dict, max_rows: int | None = None, height: int | None = None) -> None:
    """채팅 안 결과 표 — 높이·행 수 제한."""
    full = result.get("dataframe")
    preview = result.get("preview")
    source = full if isinstance(full, pd.DataFrame) and not full.empty else preview
    if not isinstance(source, pd.DataFrame) or source.empty:
        return
    max_rows = max_rows or TABLE_PREVIEW_ROWS
    height = height or TABLE_PREVIEW_HEIGHT
    total = len(full) if isinstance(full, pd.DataFrame) else result.get("shape", {}).get("rows", len(source))
    st.dataframe(
        source.head(max_rows),
        use_container_width=True,
        height=height,
        hide_index=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 프롬프트 처리
# ══════════════════════════════════════════════════════════════════════════════

def _build_files_metadata(filenames: list[str]) -> list[dict]:
    """첨부 파일의 메타데이터를 수집합니다."""
    meta = []
    for fname in filenames:
        path = EXCEL_DIR / fname
        if not path.exists():
            continue
        try:
            df = read_excel_smart(str(path))
            meta.append({
                "name": fname,
                "rows": len(df),
                "cols": len(df.columns),
                "columns": list(df.columns[:10]),
            })
        except Exception:
            meta.append({"name": fname, "rows": "?", "cols": "?"})
    return meta


def _sum_ollama_calls(calls: list[OllamaCallResult]) -> dict[str, Any]:
    prompt_t = sum(c.prompt_tokens for c in calls)
    comp_t = sum(c.completion_tokens for c in calls)
    elapsed = sum(c.elapsed_ms for c in calls)
    thinking = "\n\n---\n\n".join(c.thinking for c in calls if c.thinking)
    return {
        "tokens": {"prompt": prompt_t, "completion": comp_t, "total": prompt_t + comp_t},
        "elapsed_ms": elapsed,
        "thinking": thinking,
    }


def _prepare_enhancement(
    prompt: str,
    *,
    attached: list[str],
    persona_id: str,
    use_enh: bool,
    custom_sp: str,
    frames: dict[str, pd.DataFrame] | None = None,
    files_meta: list[dict] | None = None,
) -> tuple[str, str, dict, list[dict[str, str]], PersonaRecord | Any, str]:
    """Persona 맞춤 파이프라인 — structured prompt · 도구 실행 · 메타."""
    from src.persona_pipeline import prepare_persona_execution

    steps: list[dict[str, str]] = []
    persona_rec = get_selected_persona(persona_id)
    system_prompt = ""
    enhanced_prompt = ""
    enhancement_info = ""
    enhancement_meta: dict = {}

    if not use_enh:
        persona = get_persona(persona_id)
        system_prompt = custom_sp.strip() or persona.system_prompt
        steps.append(empty_trace_step("프롬프트 보강", "OFF — 기본 system prompt 사용"))
        st.session_state.pop("persona_execution_plan", None)
        return enhanced_prompt, enhancement_info, enhancement_meta, steps, persona_rec, system_prompt

    files_meta = files_meta if files_meta is not None else (
        _build_files_metadata(attached) if attached else []
    )
    plan = prepare_persona_execution(
        prompt,
        persona_id,
        filenames=list(attached),
        frames=frames or {},
        files_metadata=files_meta,
        custom_system_prompt=custom_sp,
        use_enhancement=True,
    )
    st.session_state.persona_execution_plan = plan
    persona_rec = plan.profile.record
    enhanced_prompt = plan.preview_text
    enhancement_info = plan.enhancement_log
    enhancement_meta = plan.enhancement_meta
    system_prompt = persona_rec.system_prompt

    for s in plan.thinking_steps:
        steps.append(empty_trace_step(s.get("label", ""), s.get("detail", "")))

    st.session_state.last_enhanced_prompt = enhanced_prompt
    st.session_state.last_enhancement_meta = enhancement_meta
    return enhanced_prompt, enhancement_info, enhancement_meta, steps, persona_rec, system_prompt


def _append_processing_turn(trace: dict[str, Any]) -> None:
    """처리 중 placeholder — UI가 멈춘 것처럼 보이지 않게."""
    st.session_state.messages.append({
        "role": "assistant",
        "content": "⏳ **처리 중입니다…** (진행 상황은 아래를 확인하세요)",
        "trace": {**trace, "status": "processing"},
        "trace_expanded": True,
        "_processing": True,
    })


def _append_assistant_turn(content: str, trace: dict[str, Any]) -> None:
    msg = {
        "role": "assistant",
        "content": content,
        "trace": trace,
        "trace_expanded": False,
    }
    if st.session_state.messages and st.session_state.messages[-1].get("_processing"):
        st.session_state.messages[-1] = msg
    else:
        st.session_state.messages.append(msg)
    _autosave_messages(st.session_state.messages)


def _complete_excel_run(
    pending: dict[str, Any],
    *,
    result: dict[str, Any],
    extra_steps: list[dict[str, str]] | None = None,
) -> None:
    """실행 완료 후 assistant 메시지·차트·저장."""
    steps = list(pending.get("trace", {}).get("thinking_steps") or [])
    if extra_steps:
        steps.extend(extra_steps)
    calls = list(pending.get("ollama_calls") or [])
    calls.extend(result.get("ollama_calls") or [])
    metrics = _sum_ollama_calls(calls)
    codegen_ms = float(
        pending.get("codegen_elapsed_ms") or pending.get("trace", {}).get("elapsed_ms") or 0
    )
    exec_ms = float(result.get("sandbox_ms") or 0)
    trace = {
        **pending.get("trace", {}),
        "thinking_steps": steps + list(result.get("thinking_steps") or []),
        "generated_code": result.get("code") or pending.get("code"),
        "tokens": metrics["tokens"],
        "thinking": metrics.get("thinking") or pending.get("trace", {}).get("thinking", ""),
        "status": "completed",
        "elapsed_ms": codegen_ms + exec_ms,
    }

    content = format_result(result)
    chart_bytes = result.get("chart_bytes")
    if result.get("dataframe") is not None:
        st.session_state["_last_result_df"] = result["dataframe"]
    if chart_bytes:
        st.session_state["_last_chart"] = chart_bytes

    trace["pipeline_stage"] = "result"
    _append_assistant_turn(content, trace)
    st.session_state.pending_excel_run = None


def handle_pending_excel_action() -> bool:
    """확인/취소 버튼 처리. 처리했으면 True."""
    action = st.session_state.pop("_excel_confirm_action", None)
    pending = st.session_state.get("pending_excel_run")
    if not action or not pending:
        return False

    if action == "cancel":
        trace = {**pending.get("trace", {}), "status": "cancelled"}
        _append_assistant_turn("실행이 취소되었습니다.", trace)
        st.session_state.pending_excel_run = None
        return True

    model = pending["model"]
    start_busy_timer("코드 실행")
    try:
        with st.chat_message("assistant"):
            trace = dict(pending.get("trace") or {})
            render_live_progress(trace, current_step="샌드박스 실행 중")
            with st.status("pandas 코드 실행 중…", expanded=True) as run_st:
                run_st.write("AST 검증 → subprocess 샌드박스 (최대 60초)")
                render_pipeline_tracker("run")
                result = execute_prepared_excel_code(
                        pending["code"],
                        pending["frames"],
                        pending["user_prompt"],
                        model,
                        thinking_steps=trace.get("thinking_steps"),
                        ollama_calls=pending.get("ollama_calls"),
                    )
                run_st.update(label="실행 완료", state="complete")
        _complete_excel_run(pending, result=result)
    finally:
        stop_busy_timer()
    return True


def process_message(prompt: str) -> None:
    """사용자 메시지 처리 — trace 표시, 엑셀은 코드 확인 후 실행."""
    if not prompt.strip():
        return
    if st.session_state.get("pending_excel_run"):
        st.warning("코드 실행 확인이 끝난 뒤에 다음 메시지를 보내주세요.")
        return

    t_turn = time.perf_counter()
    available_models = ollama_models()
    requested_model = st.session_state.get("selected_model", "")
    hw_snap = _cached_snapshot("/", str(PROJECT_ROOT))
    model = pick_safe_ollama_model(requested_model, available_models, snap=hw_snap)
    model_switched = requested_model and model != requested_model
    if model_switched:
        st.session_state.selected_model = model

    attached = _ensure_attached_files(st.session_state.get("attached_files", []))
    if not attached:
        st.session_state.messages.append({"role": "user", "content": prompt})
        _append_assistant_turn(
            "⚠️ 첨부된 Excel 파일이 없습니다. 사이드바 **📁 Excel · 파일**에서 **➕ 첨부** 후 다시 시도하세요.",
            {"user_prompt": prompt, "status": "error"},
        )
        return
    persona_id = st.session_state.get("persona_id", "general")
    use_enh = st.session_state.get("use_enhancement", True)
    custom_sp = st.session_state.get("custom_system_prompt", "")
    st.session_state.last_user_prompt = prompt

    files_meta = _build_files_metadata(attached)
    _data_ctx, _frames = build_data_context(attached)
    enhanced_prompt, enhancement_info, enhancement_meta, think_steps, persona_rec, system_prompt = (
        _prepare_enhancement(
            prompt,
            attached=attached,
            persona_id=persona_id,
            use_enh=use_enh,
            custom_sp=custom_sp,
            frames=_frames,
            files_meta=files_meta,
        )
    )
    persona_plan = st.session_state.get("persona_execution_plan")
    if not use_enh:
        st.session_state.pop("last_enhanced_prompt", None)

    user_trace: dict[str, Any] = {
        "user_prompt": prompt,
        "enhanced_prompt": enhanced_prompt if use_enh else "",
        "thinking_steps": think_steps,
        "status": "user_submitted",
    }
    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
        "trace": user_trace,
    })
    _ensure_chat_session()

    assistant_trace: dict[str, Any] = {
        "user_prompt": prompt,
        "enhanced_prompt": enhanced_prompt if use_enh else "",
        "thinking_steps": list(think_steps),
        "status": "processing",
        "pipeline_stage": "enhance",
    }

    start_busy_timer("AI 처리")
    _append_processing_turn(assistant_trace)
    try:
        with st.chat_message("assistant"):
            if enhancement_info:
                st.caption(f"✨ 보강됨 | {enhancement_info}")
            if model_switched:
                st.warning(
                    f"모델 `{requested_model}` 은 RAM이 부족해 **`{model}`** 로 실행합니다."
                )

            render_pipeline_tracker("thinking")
            render_live_progress(assistant_trace, current_step="Thinking · 코드 생성 준비")

            fast_builtin = attached and _likely_fast_builtin(prompt)
            if fast_builtin:
                hint = (
                    "집행률(%) 표 — LLM·예열 생략"
                    if _wants_execution_rate_table(prompt)
                    else "파일별 범위 — LLM·예열 생략"
                )
                think_steps.append(empty_trace_step("빠른 경로", hint))
                assistant_trace["thinking_steps"] = list(think_steps)

            if (
                model
                and not st.session_state.get("ollama_warmed")
                and not fast_builtin
            ):
                think_steps.append(empty_trace_step("모델 예열", model))
                assistant_trace["thinking_steps"] = list(think_steps)
                render_live_progress(assistant_trace, current_step="모델 GPU 예열 (최초 1회)")
                with st.status("모델 예열 중…", expanded=True) as warm_st:
                    warm_st.write("Ollama에 모델을 올리는 중입니다 (30초~2분).")
                    ollama_warmup(model)
                    warm_st.update(label="모델 예열 완료", state="complete")
                st.session_state.ollama_warmed = True

            try:
                if attached:
                    if not fast_builtin:
                        model_wait_hint(model)
                    progress_updates: list[str] = []

                    status_label = "엑셀 코드 생성 중…"
                    if fast_builtin and _wants_execution_rate_table(prompt):
                        status_label = "집행률(%) 계산 중…"
                    elif fast_builtin:
                        status_label = "파일별 범위 계산 중…"
                    with st.status(status_label, expanded=True) as pipeline_st:
                        for msg in progress_updates:
                            pipeline_st.write(msg)
                        render_live_progress(
                            assistant_trace,
                            current_step="파일 읽기 / 분석",
                        )
                        gen = generate_excel_code_only(
                            prompt,
                            attached,
                            model,
                            thinking_steps=think_steps,
                            on_progress=lambda m: (
                                progress_updates.append(m),
                                pipeline_st.write(m),
                            ),
                            use_stream=not fast_builtin,
                            persona_plan=persona_plan,
                            preloaded_frames=_frames,
                            preloaded_data_context=_data_ctx,
                        )
                        for msg in progress_updates:
                            pipeline_st.write(msg)
                        pipeline_st.update(
                            label="파일 분석 완료" if fast_builtin else "코드 생성 완료",
                            state="complete",
                        )

                    if gen.get("error"):
                        assistant_trace["status"] = "error"
                        _append_assistant_turn(f"⚠️ {gen['error']}", assistant_trace)
                        return

                    if gen.get("direct_content"):
                        turn_ms = (time.perf_counter() - t_turn) * 1000
                        assistant_trace.update({
                            "thinking_steps": gen.get("thinking_steps", think_steps),
                            "status": "completed",
                            "code_source": "persona_tools",
                            "pipeline_stage": "complete",
                            "elapsed_ms": turn_ms,
                            "tokens": {"prompt": 0, "completion": 0, "total": 0},
                        })
                        st.markdown(gen["direct_content"], unsafe_allow_html=True)
                        render_trace_metrics_footer(assistant_trace)
                        render_execution_trace(assistant_trace, expanded=False)
                        _append_assistant_turn(gen["direct_content"], assistant_trace)
                        return

                    calls = list(gen.get("ollama_calls") or [])
                    metrics = _sum_ollama_calls(calls)
                    codegen_ms = (time.perf_counter() - t_turn) * 1000
                    assistant_trace.update({
                        "generated_code": gen.get("code", ""),
                        "thinking": gen.get("gen_thinking") or metrics.get("thinking", ""),
                        "thinking_steps": gen.get("thinking_steps", think_steps),
                        "tokens": metrics["tokens"],
                        "elapsed_ms": max(float(metrics.get("elapsed_ms") or 0), codegen_ms),
                        "code_source": gen.get("code_source", "llm"),
                        "pipeline_stage": "confirm",
                    })
                    src = gen.get("code_source", "llm")
                    if src == "template":
                        assistant_trace["thinking_steps"].append(
                            empty_trace_step("코드 출처", "검증된 템플릿 (LLM 생략)"),
                        )
                    elif src == "llm":
                        assistant_trace["thinking_steps"].append(
                            empty_trace_step("코드 출처", f"Ollama 생성 · {model}"),
                        )

                    if st.session_state.get("auto_run_excel_code", False):
                        assistant_trace["thinking_steps"].append(
                            empty_trace_step("자동 실행", "코드 생성 후 즉시 샌드박스 실행"),
                        )
                        render_live_progress(assistant_trace, current_step="코드 실행 중")
                        with st.status("코드 자동 실행 중…", expanded=True) as auto_st:
                            auto_st.write("생성된 pandas 코드를 샌드박스에서 실행합니다.")
                            result = execute_prepared_excel_code(
                                gen["code"],
                                gen["frames"],
                                prompt,
                                model,
                                thinking_steps=assistant_trace["thinking_steps"],
                                ollama_calls=calls,
                            )
                            auto_st.update(label="실행 완료", state="complete")
                        turn_ms = (time.perf_counter() - t_turn) * 1000
                        assistant_trace.update({
                            "generated_code": gen["code"],
                            "status": "completed",
                            "elapsed_ms": turn_ms,
                        })
                        if result.get("ollama_calls"):
                            m2 = _sum_ollama_calls(
                                calls + list(result.get("ollama_calls") or []),
                            )
                            assistant_trace["tokens"] = m2["tokens"]
                        content = format_result(result)
                        st.markdown(content, unsafe_allow_html=True)
                        render_trace_metrics_footer(assistant_trace)
                        render_execution_trace(assistant_trace, expanded=False)
                        if result.get("dataframe") is not None:
                            st.session_state["_last_result_df"] = result["dataframe"]
                            render_result_table(result)
                        if result.get("chart_bytes"):
                            st.image(
                                result["chart_bytes"],
                                caption="📈 분석 차트",
                                use_container_width=True,
                            )
                            st.session_state["_last_chart"] = result["chart_bytes"]
                        _append_assistant_turn(content, assistant_trace)
                        return

                    assistant_trace["status"] = "awaiting_exec_confirm"
                    st.session_state.pending_excel_run = {
                        "user_prompt": prompt,
                        "model": model,
                        "code": gen["code"],
                        "frames": gen["frames"],
                        "filenames": attached,
                        "ollama_calls": calls,
                        "trace": assistant_trace,
                        "codegen_elapsed_ms": assistant_trace.get("elapsed_ms", 0),
                    }
                    render_pipeline_tracker("confirm")
                    render_live_progress(assistant_trace)
                    render_trace_metrics_footer(assistant_trace)
                    render_execution_trace(assistant_trace, expanded=True)
                    st.markdown("### 생성된 Python 코드")
                    st.code(gen["code"], language="python")
                    st.warning(
                        "**⑤ 실행 여부 확인** — 코드를 확인한 뒤 아래 **✅ 이대로 실행**을 누르면 "
                        "⑥ Python 샌드박스 실행 → ⑦ 결과가 표시됩니다."
                    )
                    st.session_state["_rerun_for_pending"] = True
                    return

                model_wait_hint(model)
                render_live_progress(
                    assistant_trace,
                    current_step=f"채팅 응답 생성 ({model})",
                )
                with st.status("AI 응답 생성 중…", expanded=True) as chat_st:
                    chat_st.write(f"모델: `{model}`")
                    think_steps.append(empty_trace_step("Ollama chat", f"모델: {model}"))
                    if use_enh and enhanced_prompt:
                        history = [
                            m for m in st.session_state.messages[:-1]
                            if m.get("role") in ("user", "assistant")
                        ]
                        messages_for_ai = history + [
                            {"role": "user", "content": enhanced_prompt},
                        ]
                    else:
                        messages_for_ai = [
                            {"role": "system", "content": system_prompt},
                        ] + st.session_state.messages
                    chat_result = ollama_chat(model, messages_for_ai)
                    chat_st.update(label="응답 수신 완료", state="complete")

                turn_ms = (time.perf_counter() - t_turn) * 1000
                assistant_trace.update({
                    "thinking_steps": think_steps + [
                        empty_trace_step("응답 수신", chat_result.usage_summary()),
                    ],
                    "thinking": chat_result.thinking,
                    "tokens": tokens_dict_from_result(chat_result),
                    "elapsed_ms": chat_result.elapsed_ms or turn_ms,
                    "status": "completed",
                })
                render_live_progress(assistant_trace)
                st.markdown(chat_result.content, unsafe_allow_html=True)
                render_trace_metrics_footer(assistant_trace)
                render_execution_trace(assistant_trace, expanded=False)
                _append_assistant_turn(chat_result.content, assistant_trace)

            except requests.ConnectionError:
                assistant_trace["status"] = "error"
                _append_assistant_turn(
                    "⚠️ Ollama 서버에 연결할 수 없습니다. `ollama serve`를 실행하세요.",
                    assistant_trace,
                )
            except Exception as exc:
                assistant_trace["status"] = "error"
                _append_assistant_turn(f"⚠️ 오류: {exc}", assistant_trace)
    finally:
        stop_busy_timer()


# ══════════════════════════════════════════════════════════════════════════════
# 사이드바
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### Basic SW Technology")
    st.caption(f"📍 SW_Tech · `{Path(__file__).resolve().name}` · 포트 8502")
    st.divider()

    # ── 모델 선택 (목업 상단) ────────────────────────────────────────────────
    st.markdown("**모델 선택**")
    available = ollama_models()
    if not available:
        st.warning("Ollama 모델 없음")
        available = ["(없음)"]

    current = st.session_state.get("selected_model", "")
    if not current or current not in available:
        current = available[0]
        st.session_state.selected_model = current

    st.selectbox(
        "모델",
        available,
        index=available.index(current),
        key="selected_model",
        label_visibility="collapsed",
    )
    sel = st.session_state.get("selected_model", current)
    _hw = _cached_snapshot("/", str(PROJECT_ROOT))
    _notice = sidebar_model_notice(
        sel,
        _hw,
        has_excel_files=bool(st.session_state.get("attached_files")),
    )
    if _notice:
        if "GPU VRAM 충분" in _notice:
            st.info(_notice)
        else:
            st.warning(_notice)

    st.divider()

    # ── 새 대화 ──────────────────────────────────────────────────────────────
    if st.button("✏️  새 대화", use_container_width=True, type="primary"):
        st.session_state.messages = []
        st.session_state.attached_files = []
        st.session_state.custom_system_prompt = ""
        st.session_state.chat_session_id = str(uuid.uuid4())
        st.session_state.active_chat_file = new_live_chat_name(st.session_state.chat_session_id)
        st.session_state.pending_excel_run = None
        st.session_state.pop("_last_result_df", None)
        st.session_state.pop("_last_chart", None)
        st.session_state.pop("active_flow_step", None)
        st.session_state.pop("flow_step_next", None)
        st.session_state.pop("_excel_confirm_action", None)
        st.session_state.step_flow = {
            "flow_id": "excel_stepwise",
            "step1": "",
            "step2": "",
            "step3": "",
        }
        st.rerun()

    render_persona_sidebar()

    with st.expander("⚙️ 고급 · 엑셀 분석", expanded=False):
        st.toggle("✨ 프롬프트 보강 (Persona 결합)", value=True, key="use_enhancement")
        st.caption("끄면 Persona 없이 기존 system prompt + 일반 메시지만 전송합니다.")
        st.toggle(
            "⚡ 빠른 모드 (코드만, 설명 LLM 생략)",
            value=True,
            key="fast_mode",
            help="Ollama 호출 1회로 줄여 응답이 훨씬 빨라집니다.",
        )
        st.toggle(
            "▶ 코드 생성 후 자동 실행 (승인 단계 생략)",
            value=False,
            key="auto_run_excel_code",
            help="기본: ⑤ 실행 확인 → ⑥ Python 실행. 켜면 코드 생성 직후 자동 실행합니다.",
        )
        if st.button("🔥 모델 GPU 예열", use_container_width=True, key="warmup_btn"):
            m = st.session_state.get("selected_model", "")
            if m and m != "(없음)":
                ollama_warmup(m)
                st.session_state.ollama_warmed = True
                st.success(f"예열 완료: {m}")
            else:
                st.info("모델을 먼저 선택하세요")

    # ── Excel · 파일 (업로드 / 목록 / 첨부 / 미리보기) ───────────────────────
    with st.expander("📁 Excel · 파일", expanded=False):
        uploads = st.file_uploader(
            "Excel / CSV 업로드",
            type=["xlsx", "xls", "csv"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        if uploads and st.button("업로드", key="upload_btn"):
            for uf in uploads:
                dest = EXCEL_DIR / uf.name
                dest.write_bytes(uf.getvalue())
            st.success(f"{len(uploads)}개 파일 저장됨")
            st.rerun()

        st.markdown("**📂 Excel 파일 목록**")
        excel_files = list_excel_files()

        if excel_files:
            for ef in excel_files:
                fname = ef["name"]
                is_attached = fname in st.session_state.attached_files
                size_str = file_size_fmt(ef["size"])
                date_str = ef["modified"].strftime("%m/%d %H:%M")

                c1, c2, c3 = st.columns([5, 1, 1])
                with c1:
                    icon = "📌" if is_attached else "📄"
                    st.caption(f"{icon} {fname}  \n  {size_str} · {date_str}")
                with c2:
                    if is_attached:
                        if st.button("➖", key=f"detach_{fname}", help="첨부 해제"):
                            st.session_state.attached_files.remove(fname)
                            st.rerun()
                    else:
                        if st.button("➕", key=f"attach_{fname}", help="첨부"):
                            st.session_state.attached_files.append(fname)
                            st.rerun()
                with c3:
                    if st.button("🗑", key=f"del_{fname}", help="삭제"):
                        (EXCEL_DIR / fname).unlink(missing_ok=True)
                        if fname in st.session_state.attached_files:
                            st.session_state.attached_files.remove(fname)
                        st.rerun()
        else:
            st.caption("파일 없음 — 위에서 업로드하세요")

        attached = st.session_state.attached_files
        st.markdown(f"**📌 첨부 파일 ({len(attached)}개)**")
        if attached:
            for fname in attached:
                st.caption(f"• {fname}")
        else:
            st.caption("파일을 ➕로 첨부하세요")

        st.markdown("**👁 파일 미리보기**")
        preview_options = [ef["name"] for ef in excel_files] if excel_files else []
        if preview_options:
            preview_file = st.selectbox(
                "미리보기 파일",
                preview_options,
                label_visibility="collapsed",
            )
            if preview_file:
                try:
                    preview_df = read_excel_smart(str(EXCEL_DIR / preview_file))
                    st.caption(f"{preview_df.shape[0]}행 × {preview_df.shape[1]}열")
                    st.dataframe(
                        preview_df.head(8),
                        use_container_width=True,
                        height=160,
                        hide_index=True,
                    )
                except Exception as e:
                    st.error(f"미리보기 실패: {e}")
        else:
            st.caption("미리볼 파일 없음")

    st.divider()

    # ── 내보내기 ─────────────────────────────────────────────────────────────
    st.markdown("**💾 내보내기**")
    exp_c1, exp_c2 = st.columns(2)
    def _snapshot_on_download() -> None:
        msgs = st.session_state.get("messages") or []
        if not msgs:
            return
        _autosave_messages(msgs)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        md_path = save_conversation_md(msgs, f"chat_{ts}")
        st.session_state["_last_saved_chat"] = str(md_path)

    with exp_c1:
        chat_msgs = st.session_state.get("messages") or []
        if chat_msgs:
            export_title = _chat_summary_title(chat_msgs)
            export_md = messages_to_markdown(chat_msgs, summary_title=export_title)
            export_name = f"chat_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            st.download_button(
                "📥 대화 저장",
                data=export_md.encode("utf-8"),
                file_name=export_name,
                mime="text/markdown",
                use_container_width=True,
                help="MD 파일 다운로드 + results/ 스냅샷 저장",
                on_click=_snapshot_on_download,
                key="download_chat_md",
            )
        else:
            st.button(
                "📥 대화 저장",
                disabled=True,
                use_container_width=True,
                help="대화가 없습니다",
            )
    with exp_c2:
        last_df = st.session_state.get("_last_result_df")
        if last_df is not None:
            st.download_button(
                "📥 Excel",
                data=dataframe_to_bytes(last_df),
                file_name=f"result_{datetime.datetime.now().strftime('%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.button("📥 Excel", disabled=True, use_container_width=True, help="결과 없음")

    last_chart = st.session_state.get("_last_chart")
    if last_chart:
        st.download_button(
            "📥 차트 (PNG)",
            data=last_chart,
            file_name=f"chart_{datetime.datetime.now().strftime('%H%M%S')}.png",
            mime="image/png",
            use_container_width=True,
        )

    if st.session_state.get("_last_saved_chat"):
        st.success(f"저장됨: `{Path(st.session_state['_last_saved_chat']).name}`")

    st.divider()

    render_busy_timer_fragment()

    saved_chats = list_saved_chats()
    st.markdown(f"**📜 저장된 대화 ({len(saved_chats)}건)**")
    render_saved_chats_section(saved_chats, load_fn=load_conversation_md)

    st.divider()

    render_step_flow_sidebar(saved_chats)

    if st.session_state.get("last_enhanced_prompt"):
        render_enhanced_prompt_preview(
            st.session_state.last_enhanced_prompt,
            st.session_state.get("last_enhancement_meta"),
        )

    st.divider()
    render_settings_section()


# ══════════════════════════════════════════════════════════════════════════════
# 메인 영역 — 대시보드 + 채팅
# ══════════════════════════════════════════════════════════════════════════════

render_page_title()
render_dashboard_top(st.session_state.get("selected_model", ""))

st.markdown("### 채팅")

SUGGESTIONS = [
    ("📊 파일 구조 분석", "첨부된 엑셀 파일의 컬럼 구조와 데이터 유형을 분석해주세요."),
    ("🔀 파일 병합", "첨부된 모든 엑셀 파일을 하나로 병합하고, 중복 컬럼은 평균값으로 처리해주세요."),
    ("📈 예산 집행률", "계획예산 대비 집행계의 집행률(%)을 계산하고 높은 순으로 정렬해주세요."),
    (
        "📊 차트 시각화",
        "비목분류별 계획예산·당해집행으로 집행률(%)을 계산하고, "
        "집행률 상위 15개만 막대 차트로 그려주세요. "
        "차트는 dropna로 행 단위 정렬 후 plot_df만 사용하세요.",
    ),
]

messages: list[dict] = st.session_state.get("messages", [])
pending: str = st.session_state.get("pending_prompt", "")
pending_excel = st.session_state.get("pending_excel_run")

if st.session_state.get("_flow_execute_requested"):
    if handle_flow_execution():
        st.rerun()

if st.session_state.get("_excel_confirm_action"):
    if handle_pending_excel_action():
        st.rerun()

if pending:
    st.session_state.pending_prompt = ""
    _inject_flow_step_header()
    messages = st.session_state.get("messages", [])
    for msg in messages:
        with st.chat_message(msg["role"]):
            render_message_with_trace(msg)
    with st.chat_message("user"):
        st.markdown(pending)
    process_message(pending)

elif not messages and not pending_excel:
    st.caption("메시지를 입력하거나, 아래 제안으로 엑셀 분석을 시작하세요. (사이드바에서 파일 ➕ 첨부)")

    col_a, col_b = st.columns(2)
    for i, (label, prompt_text) in enumerate(SUGGESTIONS):
        target = col_a if i % 2 == 0 else col_b
        with target:
            st.markdown('<div class="chip-col">', unsafe_allow_html=True)
            if st.button(label, key=f"chip_{i}", use_container_width=True):
                st.session_state.pending_prompt = prompt_text
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

else:
    for i, msg in enumerate(messages):
        is_last = i == len(messages) - 1
        with st.chat_message(msg["role"]):
            render_message_with_trace(msg)
            if (
                is_last
                and msg.get("role") == "assistant"
                and st.session_state.get("_last_result_df") is not None
            ):
                render_result_table({
                    "dataframe": st.session_state["_last_result_df"],
                    "preview": st.session_state["_last_result_df"].head(TABLE_PREVIEW_ROWS),
                    "shape": {
                        "rows": len(st.session_state["_last_result_df"]),
                        "cols": len(st.session_state["_last_result_df"].columns),
                    },
                })
            if is_last and msg.get("role") == "assistant" and st.session_state.get("_last_chart"):
                st.image(
                    st.session_state["_last_chart"],
                    caption="📈 분석 차트",
                    use_container_width=True,
                )

    if pending_excel:
        with st.chat_message("assistant"):
            if render_pending_excel_confirm(pending_excel):
                st.rerun()

# ── 채팅 입력 ────────────────────────────────────────────────────────────────
_chat_disabled = bool(st.session_state.get("pending_excel_run"))
if user_input := st.chat_input(
    "메시지를 입력하세요..." if not _chat_disabled else "코드 실행 확인 후 입력 가능…",
    disabled=_chat_disabled,
):
    with st.chat_message("user"):
        st.markdown(user_input)
    process_message(user_input)
    st.rerun()

if st.session_state.pop("_rerun_for_pending", False):
    st.rerun()
