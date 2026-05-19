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

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

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


def ollama_chat(model: str, messages: list[dict], temperature: float = 0.3) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
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


def ollama_generate(model: str, prompt: str, temperature: float = 0.2) -> str:
    """단일 프롬프트를 /api/chat 으로 전송 (generate 보다 안정적)."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": temperature},
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
    return df


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
    if not s:
        return pd.NA
    try:
        return int(s) if "." not in s else float(s)
    except ValueError:
        return pd.NA


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

        runner = textwrap.dedent(f"""\
        import pandas as pd
        import numpy as np
        import json, os, pickle

        tmpdir = {tmpdir!r}
        frames = {{}}
        for f in os.listdir(tmpdir):
            if f.endswith('.pkl'):
                frames[f[:-4]] = pd.read_pickle(os.path.join(tmpdir, f))

        # 사용자 코드에서 사용할 수 있도록 개별 변수로 할당
        for _name, _df in frames.items():
            globals()[_name] = _df

        # ── 사용자 코드 ──
        {textwrap.indent(code, '        ').strip()}
        # ── 끝 ──

        # result 변수를 찾아서 저장
        if 'result' in dir():
            r = result
        else:
            # 마지막으로 만들어진 DataFrame 찾기
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

        if os.path.exists(result_pkl):
            import json
            result_df = pd.read_pickle(result_pkl)
            with open(info_json) as fp:
                info = json.load(fp)
            return {
                "dataframe": result_df,
                "shape": info,
                "preview": result_df.head(20),
            }
        elif os.path.exists(scalar_txt):
            with open(scalar_txt) as fp:
                return {"scalar": fp.read().strip()}
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
        context_parts.append(
            f"### {var_name} = '{fname}'\n"
            f"- Shape: {df.shape[0]}행 × {df.shape[1]}열\n"
            f"- Columns: {list(df.columns)}\n"
            f"- dtypes:\n{textwrap.indent(df.dtypes.to_string(), '  ')}\n"
            f"- Head (3 rows):\n{textwrap.indent(df.head(3).to_string(), '  ')}\n"
        )

    return "\n".join(context_parts), frames


def generate_code_prompt(user_prompt: str, data_context: str, frame_names: list[str]) -> str:
    return textwrap.dedent(f"""\
    당신은 pandas/numpy 전문가입니다. 사용자의 요청을 수행하는 Python 코드를 생성하세요.

    ## 규칙
    1. pandas와 numpy만 사용 가능합니다.
    2. 결과를 `result` 변수에 DataFrame으로 저장하세요.
    3. 사용 가능한 DataFrame 변수: {', '.join(frame_names)}
    4. 코드만 출력하세요 — 설명이나 마크다운 없이 순수 Python 코드만.
    5. print() 사용 금지. 결과는 반드시 result 변수에 할당.
    6. 한글 컬럼명을 그대로 사용하세요.

    ## 데이터 정보
    {data_context}

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
) -> dict:
    """자연어 프롬프트로 엑셀 처리: 코드 생성 → 실행 → 설명."""
    data_context, frames = build_data_context(filenames)
    if not frames:
        return {"error": "첨부된 파일을 읽을 수 없습니다."}

    code_prompt = generate_code_prompt(user_prompt, data_context, list(frames.keys()))

    try:
        raw_code = ollama_generate(model, code_prompt, temperature=0.1)
    except Exception as e:
        hint = ""
        err = str(e).lower()
        if "memory" in err or "system memory" in err:
            hint = " 사이드바에서 **qwen2.5:7b** 등 작은 모델을 선택하세요."
        return {"error": f"AI 코드 생성 실패: {e}{hint}"}

    code = extract_code_block(raw_code)
    if not code:
        return {"error": "AI가 유효한 코드를 생성하지 못했습니다.", "raw": raw_code}

    exec_result = execute_pandas_code(code, frames)

    if "error" in exec_result:
        return {**exec_result, "code": code}

    explanation = ""
    try:
        explain_prompt = (
            f"다음 pandas 코드의 실행 결과를 한국어로 간결하게 설명하세요.\n"
            f"코드:\n```python\n{code}\n```\n"
        )
        if "shape" in exec_result:
            explain_prompt += f"결과: {exec_result['shape']['rows']}행 × {exec_result['shape']['cols']}열"
        elif "scalar" in exec_result:
            explain_prompt += f"결과: {exec_result['scalar']}"
        explanation = ollama_generate(model, explain_prompt, temperature=0.3)
    except Exception:
        explanation = "설명 생성을 건너뛰었습니다."

    return {**exec_result, "code": code, "explanation": explanation}


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
    return path


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

    if result.get("preview") is not None:
        try:
            parts.append(result["preview"].to_markdown(index=False))
        except ImportError:
            parts.append(result["preview"].to_string(index=False))

    if result.get("scalar"):
        parts.append(f"📊 결과: **{result['scalar']}**")

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


# ══════════════════════════════════════════════════════════════════════════════
# 프롬프트 처리
# ══════════════════════════════════════════════════════════════════════════════

def process_message(prompt: str) -> None:
    if not prompt.strip():
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    model = st.session_state.get("selected_model", "")
    attached = st.session_state.get("attached_files", [])

    with st.chat_message("assistant"):
        with st.spinner("AI 처리 중..."):
            try:
                if attached:
                    result = process_excel_prompt(prompt, attached, model)
                    content = format_result(result)
                    if result.get("dataframe") is not None:
                        st.session_state["_last_result_df"] = result["dataframe"]
                else:
                    messages_for_ai = [
                        {"role": "system", "content": (
                            "당신은 엑셀 데이터 분석 전문가입니다. "
                            "한국어로 답변하세요. "
                            "엑셀 파일이 첨부되지 않은 경우, 분석 방법을 안내하세요."
                        )}
                    ] + st.session_state.messages
                    content = ollama_chat(model, messages_for_ai)
            except requests.ConnectionError:
                content = "⚠️ Ollama 서버에 연결할 수 없습니다. `ollama serve`를 실행하세요."
            except Exception as exc:
                content = f"⚠️ 오류: {exc}"

        st.markdown(content, unsafe_allow_html=True)

    st.session_state.messages.append({"role": "assistant", "content": content})


# ══════════════════════════════════════════════════════════════════════════════
# 사이드바
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 📊 AI Excel Agent Studio")
    st.divider()

    # ── 새 대화 ──────────────────────────────────────────────────────────────
    if st.button("✏️  새 대화", use_container_width=True, type="primary"):
        st.session_state.messages = []
        st.session_state.attached_files = []
        st.session_state.pop("_last_result_df", None)
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
    if any(x in current for x in ("30b", "70b", "deepseek-coder")):
        st.caption("⚠️ 대형 모델은 RAM 부족 시 실패할 수 있습니다. **qwen2.5:7b** 권장.")

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
                st.dataframe(preview_df.head(8), use_container_width=True, height=220)
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
                st.success(f"저장: {md_path.name}")
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
    ("📋 데이터 범위", "각 시트별 데이터가 채워진 행과 열의 범위를 알려주세요."),
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
