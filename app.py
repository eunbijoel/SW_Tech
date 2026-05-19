"""
AI Excel Agent Studio — Streamlit 기반 AI 엑셀 분석 도구
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
import uuid
from pathlib import Path
from typing import Any

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
    page_title="AI Excel Agent Studio",
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


def pick_safe_ollama_model(model: str, available: list[str]) -> str:
    """대형 모델이면 qwen2.5:7b 등 경량 모델로 대체."""
    if model and not is_heavy_ollama_model(model):
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


def ollama_chat(
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
    options: dict[str, Any] | None = None,
) -> str:
    opts = {**(options or OLLAMA_OPTS_CHAT), "temperature": temperature}
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": opts,
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
    if r.status_code != 200:
        try:
            err_msg = r.json().get("error", r.text)
        except Exception:
            err_msg = r.text
        raise RuntimeError(f"Ollama 오류 ({r.status_code}): {err_msg}")
    content = r.json()["message"]["content"]
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    return content


def ollama_generate(
    model: str,
    prompt: str,
    temperature: float = 0.2,
    options: dict[str, Any] | None = None,
) -> str:
    """단일 프롬프트를 /api/chat 으로 전송 (generate 보다 안정적)."""
    opts = {**(options or OLLAMA_OPTS_CODE), "temperature": temperature}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": opts,
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
    if r.status_code != 200:
        try:
            err_msg = r.json().get("error", r.text)
        except Exception:
            err_msg = r.text
        raise RuntimeError(f"Ollama 오류 ({r.status_code}): {err_msg}")
    content = r.json()["message"]["content"]
    # qwen3 계열은 <think>...</think> 블록을 포함할 수 있으므로 제거
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    return content


# ══════════════════════════════════════════════════════════════════════════════
# 페르소나 & 프롬프트 보강 (로컬 — 백엔드 불필요)
# ══════════════════════════════════════════════════════════════════════════════
from services.persona_service import get_persona, list_personas, Persona
from services.prompt_enhancer import enhance as enhance_prompt, detect_intent


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


def _columns_reference_block(frames: dict[str, pd.DataFrame]) -> str:
    """AI가 컬럼명을 오타내지 않도록 repr 문자열 목록 제공."""
    lines = ["## 사용 가능한 컬럼명 (아래 문자열을 그대로 복사 — 한자 算/산 혼동 금지)"]
    for var_name, df in frames.items():
        cols_repr = ", ".join(repr(c) for c in df.columns)
        lines.append(f"- {var_name}: {cols_repr}")
    lines.append(
        "- 예: `df['계획예산']` (O) / `df['계획예算']` (X — KeyError)\n"
        "- 여러 파일 통합: `pd.concat([df_0.assign(출처='4예실'), df_1.assign(출처='5예실'), ...])`"
    )
    return "\n".join(lines)


def generate_code_prompt(
    user_prompt: str,
    data_context: str,
    frame_names: list[str],
    frames: dict[str, pd.DataFrame] | None = None,
    prev_error: str | None = None,
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
    - 예시 (올바른 코드):
      ```
      result['집행률'] = ...
      plot_df = result.dropna(subset=['집행률', '비목분류']).head(15)
      plt.bar(plot_df['비목분류'].astype(str), plot_df['집행률'])
      ```

    {error_section}
    ## 데이터 정보
    {data_context}

    {_columns_reference_block(frames) if frames else ""}

    ## 사용자 요청
    {user_prompt}

    ## Python 코드 (result 변수에 결과 저장):
    """)


def extract_code_block(text: str) -> str:
    """AI 응답에서 Python 코드 블록을 추출."""
    patterns = [
        r"```python\s*\n(.*?)```",
        r"```\s*\n(.*?)```",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            return m.group(1).strip()

    lines = text.strip().split("\n")
    code_lines = [
        l for l in lines
        if not l.startswith("#") or "import" in l or "=" in l
    ]
    return "\n".join(code_lines).strip()


def process_excel_prompt(
    user_prompt: str,
    filenames: list[str],
    model: str,
    max_retries: int = 2,
) -> dict:
    """자연어 프롬프트로 엑셀 처리: 코드 생성 → 실행 → (실패 시 최대 2회 재시도) → 설명."""
    data_context, frames = build_data_context(filenames)
    if not frames:
        return {"error": "첨부된 파일을 읽을 수 없습니다."}

    prev_error: str | None = None
    last_code = ""
    attempts = max_retries + 1 if len(frames) <= 2 else 2  # 파일 3개↑면 재시도 1회만

    for attempt in range(attempts):
        code_prompt = generate_code_prompt(
            user_prompt,
            data_context,
            list(frames.keys()),
            frames=frames,
            prev_error=prev_error,
        )

        try:
            raw_code = ollama_generate(
                model, code_prompt, temperature=0.1, options=OLLAMA_OPTS_CODE,
            )
        except Exception as e:
            hint = ""
            err = str(e).lower()
            if "memory" in err or "system memory" in err:
                hint = " 사이드바에서 **qwen2.5:7b** 등 작은 모델을 선택하세요."
            return {"error": f"AI 코드 생성 실패: {e}{hint}"}

        code = extract_code_block(raw_code)
        if not code:
            return {"error": "AI가 유효한 코드를 생성하지 못했습니다.", "raw": raw_code}

        last_code = code
        exec_result = execute_pandas_code(code, frames)

        if "error" not in exec_result:
            break
        prev_error = f"코드:\n{code}\n\n오류:\n{exec_result['error']}"
    else:
        return {**exec_result, "code": last_code}

    explanation = ""
    if not st.session_state.get("fast_mode", True):
        try:
            explain_prompt = (
                f"다음 pandas 실행 결과를 한국어 3문장으로 요약하세요.\n"
                f"결과 shape: {exec_result.get('shape', exec_result.get('scalar', 'N/A'))}\n"
            )
            explanation = ollama_generate(
                model, explain_prompt, temperature=0.3, options=OLLAMA_OPTS_EXPLAIN,
            )
        except Exception:
            explanation = "설명 생성을 건너뛰었습니다."
    else:
        if "shape" in exec_result:
            explanation = (
                f"표 결과 {exec_result['shape']['rows']}행 × "
                f"{exec_result['shape']['cols']}열 (빠른 모드: LLM 설명 생략)"
            )

    retry_note = ""
    if prev_error:
        retry_note = f"\n\n_🔄 자동 재시도로 오류를 수정했습니다 (시도 {attempt + 1}회)_"

    return {**exec_result, "code": code, "explanation": explanation + retry_note}


# ══════════════════════════════════════════════════════════════════════════════
# 결과 내보내기
# ══════════════════════════════════════════════════════════════════════════════

def save_result_excel(df: pd.DataFrame, name: str) -> Path:
    path = RESULTS_DIR / f"{name}.xlsx"
    df.to_excel(path, index=False, engine="openpyxl")
    return path


def save_conversation_md(messages: list[dict], name: str) -> Path:
    path = RESULTS_DIR / f"{name}.md"
    lines = [f"# AI Excel Agent Studio 대화 기록\n",
             f"생성일: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n---\n"]
    for msg in messages:
        role = "👤 사용자" if msg["role"] == "user" else "🤖 AI"
        lines.append(f"\n## {role}\n\n{msg['content']}\n")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path.resolve()


def list_saved_chats(limit: int = 30) -> list[dict]:
    """results/ 아래 chat_*.md 목록 (최신순)."""
    items: list[dict] = []
    for p in RESULTS_DIR.glob("chat_*.md"):
        stat = p.stat()
        items.append({
            "name": p.name,
            "path": p.resolve(),
            "mtime": datetime.datetime.fromtimestamp(stat.st_mtime),
            "size": stat.st_size,
        })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:limit]


def load_conversation_md(path: Path) -> list[dict]:
    """저장된 .md 대화를 messages 형식으로 복원."""
    text = path.read_text(encoding="utf-8")
    messages: list[dict] = []
    parts = re.split(r"^## (👤 사용자|🤖 AI)\s*\n", text, flags=re.MULTILINE)
    for i in range(1, len(parts), 2):
        label = parts[i]
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if not content:
            continue
        role = "user" if "사용자" in label else "assistant"
        messages.append({"role": role, "content": content})
    return messages


def dataframe_to_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


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


def process_message(prompt: str) -> None:
    """사용자 메시지를 처리하고 AI 응답을 생성합니다."""
    if not prompt.strip():
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    available_models = ollama_models()
    requested_model = st.session_state.get("selected_model", "")
    model = pick_safe_ollama_model(requested_model, available_models)
    model_switched = requested_model and model != requested_model
    if model_switched:
        st.session_state.selected_model = model
    attached = st.session_state.get("attached_files", [])
    persona_id = st.session_state.get("persona_id", "general")
    use_enh = st.session_state.get("use_enhancement", True)
    custom_sp = st.session_state.get("custom_system_prompt", "")

    # 프롬프트 보강
    enhancement_info = ""
    if use_enh:
        files_meta = _build_files_metadata(attached) if attached else []
        enh = enhance_prompt(
            user_message=prompt,
            persona_id=persona_id,
            files_metadata=files_meta,
            custom_system_prompt=custom_sp if custom_sp.strip() else None,
        )
        system_prompt = enh["enhanced_system_prompt"]
        enhancement_info = enh["enhancement_log"]
    else:
        persona = get_persona(persona_id)
        system_prompt = custom_sp.strip() if custom_sp.strip() else persona.system_prompt

    with st.chat_message("assistant"):
        if enhancement_info:
            st.caption(f"✨ 보강됨 | {enhancement_info}")
        if model_switched:
            st.warning(
                f"모델 `{requested_model}` 은 RAM이 부족해 **`{model}`** 로 실행합니다. "
                "사이드바에서 qwen2.5:7b를 직접 선택하는 것을 권장합니다."
            )
        if model and not st.session_state.get("ollama_warmed"):
            with st.spinner("모델 준비 중 (최초 1회)…"):
                ollama_warmup(model)
            st.session_state.ollama_warmed = True
        chart_bytes = None
        result: dict = {}
        with st.spinner("AI 처리 중..."):
            try:
                if attached:
                    result = process_excel_prompt(prompt, attached, model)
                    content = format_result(result)
                    if result.get("dataframe") is not None:
                        st.session_state["_last_result_df"] = result["dataframe"]
                    chart_bytes = result.get("chart_bytes")
                else:
                    messages_for_ai = [
                        {"role": "system", "content": system_prompt}
                    ] + st.session_state.messages
                    content = ollama_chat(model, messages_for_ai)
            except requests.ConnectionError:
                content = "⚠️ Ollama 서버에 연결할 수 없습니다. `ollama serve`를 실행하세요."
            except Exception as exc:
                content = f"⚠️ 오류: {exc}"

        st.markdown(content, unsafe_allow_html=True)
        if attached and (
            result.get("dataframe") is not None or result.get("preview") is not None
        ):
            render_result_table(result)
        if chart_bytes:
            st.image(chart_bytes, caption="📈 분석 차트", use_container_width=True)
            st.session_state["_last_chart"] = chart_bytes

    st.session_state.messages.append({"role": "assistant", "content": content})


# ══════════════════════════════════════════════════════════════════════════════
# 사이드바
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 📊 AI Excel Agent Studio")
    st.caption(f"📍 SW_Tech · `{Path(__file__).resolve().name}` · 라이트 테마")
    st.divider()

    # ── 새 대화 ──────────────────────────────────────────────────────────────
    if st.button("✏️  새 대화", use_container_width=True, type="primary"):
        st.session_state.messages = []
        st.session_state.attached_files = []
        st.session_state.custom_system_prompt = ""
        st.session_state.pop("_last_result_df", None)
        st.session_state.pop("_last_chart", None)
        st.rerun()

    st.divider()

    # ── 페르소나 선택 ────────────────────────────────────────────────────────
    st.markdown("**🎭 페르소나**")
    all_personas = list_personas()
    persona_labels = {p.id: f"{p.emoji} {p.name}" for p in all_personas}
    persona_ids = list(persona_labels.keys())

    current_persona = st.session_state.get("persona_id", "general")
    if current_persona not in persona_ids:
        current_persona = "general"

    st.selectbox(
        "페르소나",
        persona_ids,
        index=persona_ids.index(current_persona),
        format_func=lambda pid: persona_labels[pid],
        key="persona_id",
        label_visibility="collapsed",
    )
    selected_persona = get_persona(st.session_state.persona_id)
    st.caption(f"_{selected_persona.description}_")

    st.divider()

    # ── 프롬프트 보강 토글 ──────────────────────────────────────────────────
    st.toggle("✨ 프롬프트 보강", value=True, key="use_enhancement")
    st.toggle(
        "⚡ 빠른 모드 (코드만, 설명 LLM 생략)",
        value=True,
        key="fast_mode",
        help="Ollama 호출 1회로 줄여 응답이 훨씬 빨라집니다.",
    )
    if st.button("🔥 모델 GPU 예열", use_container_width=True, help="qwen2.5:7b 등을 미리 로드"):
        m = st.session_state.get("selected_model", "")
        if m and m != "(없음)":
            ollama_warmup(m)
            st.session_state.ollama_warmed = True
            st.success(f"예열 완료: {m}")
        else:
            st.info("모델을 먼저 선택하세요")

    # ── 시스템 프롬프트 뷰어 ────────────────────────────────────────────────
    with st.expander("🔍 현재 시스템 프롬프트", expanded=False):
        default_sp = selected_persona.system_prompt
        st.text_area(
            "시스템 프롬프트 (수정 가능)",
            value=st.session_state.get("custom_system_prompt", "") or default_sp,
            height=200,
            key="custom_system_prompt",
            label_visibility="collapsed",
        )
        if st.button("기본값 복원", key="reset_sp"):
            st.session_state.custom_system_prompt = ""
            st.rerun()

    st.divider()

    # ── 모델 선택 ────────────────────────────────────────────────────────────
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
    if is_heavy_ollama_model(sel):
        st.warning(
            f"`{sel}` 은 RAM 40GB+ 가 필요할 수 있습니다. "
            "엑셀 분석은 **qwen2.5:7b** 를 선택하세요."
        )

    st.divider()

    # ── 파일 업로드 ──────────────────────────────────────────────────────────
    with st.expander("📁 파일 업로드", expanded=False):
        uploads = st.file_uploader(
            "Excel / CSV 파일",
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

    st.divider()

    # ── 파일 목록 & 첨부 ────────────────────────────────────────────────────
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

    st.divider()

    # ── 첨부된 파일 ──────────────────────────────────────────────────────────
    attached = st.session_state.attached_files
    st.markdown(f"**📌 첨부 파일 ({len(attached)}개)**")
    if attached:
        for fname in attached:
            st.caption(f"• {fname}")
    else:
        st.caption("파일을 ➕로 첨부하세요")

    st.divider()

    # ── 파일 미리보기 ────────────────────────────────────────────────────────
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
        st.caption("파일 없음")

    st.divider()

    # ── 내보내기 ─────────────────────────────────────────────────────────────
    st.markdown("**💾 내보내기**")
    exp_c1, exp_c2 = st.columns(2)
    with exp_c1:
        if st.button("📥 대화 저장", use_container_width=True, help="대화를 .md로 저장"):
            if st.session_state.messages:
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                md_path = save_conversation_md(st.session_state.messages, f"chat_{ts}")
                st.session_state["_last_saved_chat"] = str(md_path)
                st.rerun()
            else:
                st.info("대화가 없습니다")
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

    saved_chats = list_saved_chats()
    st.markdown(f"**📜 저장된 대화 ({len(saved_chats)}건)**")
    if not saved_chats:
        st.caption("대화 저장을 누르면 여기에 목록이 쌓입니다.")
    else:
        for item in saved_chats:
            fname = item["name"]
            mtime_str = item["mtime"].strftime("%m/%d %H:%M")
            preview_user = ""
            try:
                msgs = load_conversation_md(Path(item["path"]))
                for m in msgs:
                    if m["role"] == "user":
                        preview_user = m["content"][:40].replace("\n", " ")
                        break
            except Exception:
                pass

            label = preview_user or fname
            with st.expander(f"{mtime_str} · {label}", expanded=False):
                st.caption(fname)
                c_load, c_dl, c_del = st.columns([2, 1, 1])
                with c_load:
                    if st.button("불러오기", key=f"load_chat_{fname}", use_container_width=True):
                        st.session_state.messages = load_conversation_md(Path(item["path"]))
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
                            key=f"dl_chat_{fname}",
                            use_container_width=True,
                        )
                    except Exception:
                        pass
                with c_del:
                    if st.button("🗑", key=f"del_chat_{fname}", use_container_width=True):
                        Path(item["path"]).unlink(missing_ok=True)
                        st.rerun()

    st.divider()

    # ── 서버 상태 ────────────────────────────────────────────────────────────
    healthy = ollama_health()
    st.caption(f"{'🟢' if healthy else '🔴'} Ollama {'연결됨' if healthy else '연결 안 됨'}")


# ══════════════════════════════════════════════════════════════════════════════
# 메인 영역
# ══════════════════════════════════════════════════════════════════════════════

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

if pending:
    st.session_state.pending_prompt = ""
    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"], unsafe_allow_html=True)
    with st.chat_message("user"):
        st.markdown(pending)
    process_message(pending)

elif not messages:
    # ── 시작 화면 ────────────────────────────────────────────────────────────
    st.markdown("""
<div style="text-align:center; margin-top:12vh; margin-bottom:2rem;">
    <h1 style="font-size:2.5rem; font-weight:700; color:#1d1d1f; margin-bottom:0.4rem;">
        AI Excel Agent Studio
    </h1>
    <p style="color:#6e6e73; font-size:1.05rem;">
        엑셀 파일을 첨부하고 자연어로 분석·병합·변환하세요
    </p>
</div>
""", unsafe_allow_html=True)

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
    # ── 대화 기록 ────────────────────────────────────────────────────────────
    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"], unsafe_allow_html=True)

# ── 채팅 입력 ────────────────────────────────────────────────────────────────
if user_input := st.chat_input("엑셀 분석 요청을 입력하세요..."):
    with st.chat_message("user"):
        st.markdown(user_input)
    process_message(user_input)
