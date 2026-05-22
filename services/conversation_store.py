"""대화 저장·복원 — trace 메타데이터 포함 MD."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

RESULTS_DIR = Path("./results")
TRACE_MARKER = "<!--sw_trace:"


def ensure_results_dir() -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    return RESULTS_DIR


def new_live_chat_name(session_id: str) -> str:
    short = session_id.replace("-", "")[:8]
    return f"chat_live_{short}.md"


def messages_to_markdown(
    messages: list[dict],
    *,
    title: str | None = None,
    summary_title: str | None = None,
) -> str:
    """messages + trace → MD 본문."""
    heading = title or "# Basic SW Technology 대화 기록"
    lines = [heading]
    if summary_title:
        lines.append(f"title: {summary_title}")
    lines.extend([
        f"저장: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
    ])
    turn = 0
    for msg in messages:
        role = msg.get("role", "user")
        content = (msg.get("content") or "").strip()
        trace = msg.get("trace")
        if role == "user":
            turn += 1
            lines.append(f"## Turn {turn} — 👤 사용자\n")
            if trace and trace.get("user_prompt"):
                lines.append(f"{trace['user_prompt'].strip()}\n")
            else:
                lines.append(f"{content}\n")
            if trace:
                lines.append(_trace_block_md(trace, phase="input"))
        elif role == "assistant":
            lines.append(f"## Turn {turn} — 🤖 AI\n")
            if trace:
                lines.append(_trace_block_md(trace, phase="assistant"))
            lines.append(f"{content}\n")
        lines.append("")
    return "\n".join(lines)


def _trace_block_md(trace: dict[str, Any], *, phase: str) -> str:
    payload = {k: v for k, v in trace.items() if v is not None and v != ""}
    parts = [f"{TRACE_MARKER}{json.dumps(payload, ensure_ascii=False)}-->"]
    if phase == "input":
        if trace.get("enhanced_prompt"):
            parts.append("\n### 강화된 프롬프트\n")
            parts.append(f"```\n{trace['enhanced_prompt']}\n```\n")
    if trace.get("generated_code"):
        parts.append("\n### 생성된 코드\n")
        parts.append(f"```python\n{trace['generated_code']}\n```\n")
    if trace.get("thinking_steps"):
        parts.append("\n### Thinking process\n")
        for i, step in enumerate(trace["thinking_steps"], 1):
            label = step.get("label", step) if isinstance(step, dict) else str(step)
            detail = step.get("detail", "") if isinstance(step, dict) else ""
            parts.append(f"{i}. **{label}**")
            if detail:
                parts.append(f"   - {detail}")
        parts.append("")
    if trace.get("thinking"):
        parts.append("\n### 모델 Thinking\n")
        parts.append(f"```\n{trace['thinking']}\n```\n")
    metrics = []
    if trace.get("elapsed_ms") is not None:
        metrics.append(f"실행 시간: {float(trace['elapsed_ms']):.0f} ms")
    tok = trace.get("tokens") or {}
    if tok:
        metrics.append(
            f"토큰 — prompt: {tok.get('prompt', 0):,}, "
            f"completion: {tok.get('completion', 0):,}, "
            f"total: {tok.get('total', 0):,}"
        )
    if metrics:
        parts.append("\n### 메트릭\n")
        parts.append("\n".join(f"- {m}" for m in metrics))
        parts.append("\n")
    return "\n".join(parts)


_TRACE_JSON_RE = re.compile(
    re.escape(TRACE_MARKER) + r"(.*?)-->",
    re.DOTALL,
)


def markdown_to_messages(text: str) -> list[dict]:
    """MD → messages (trace 복원)."""
    messages: list[dict] = []
    chunks = re.split(r"^## Turn \d+ — (👤 사용자|🤖 AI)\s*\n", text, flags=re.MULTILINE)
    i = 1
    while i < len(chunks):
        label = chunks[i]
        body = chunks[i + 1] if i + 1 < len(chunks) else ""
        i += 2
        trace = _extract_trace_from_body(body)
        body_clean = _TRACE_JSON_RE.sub("", body)
        body_clean = re.sub(r"^### .+?\n", "", body_clean, flags=re.MULTILINE)
        body_clean = re.sub(r"```[\w]*\n.*?```", "", body_clean, flags=re.DOTALL)
        content = body_clean.strip()
        if "사용자" in label:
            user_text = (trace or {}).get("user_prompt") or content
            messages.append({
                "role": "user",
                "content": user_text,
                **({"trace": trace} if trace else {}),
            })
        else:
            if not content and trace:
                content = "(응답)"
            messages.append({
                "role": "assistant",
                "content": content,
                **({"trace": trace} if trace else {}),
            })
    if messages:
        return messages
    return _legacy_md_parse(text)


def _extract_trace_from_body(body: str) -> dict[str, Any] | None:
    m = _TRACE_JSON_RE.search(body)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _legacy_md_parse(text: str) -> list[dict]:
    messages: list[dict] = []
    parts = re.split(r"^## (👤 사용자|🤖 AI)\s*\n", text, flags=re.MULTILINE)
    for j in range(1, len(parts), 2):
        label = parts[j]
        content = parts[j + 1].strip() if j + 1 < len(parts) else ""
        if not content:
            continue
        role = "user" if "사용자" in label else "assistant"
        messages.append({"role": role, "content": content})
    return messages


def save_messages(
    messages: list[dict],
    filename: str,
    *,
    results_dir: Path | None = None,
    summary_title: str | None = None,
) -> Path:
    root = results_dir or ensure_results_dir()
    path = root / filename
    if not filename.endswith(".md"):
        path = root / f"{filename}.md"
    path.write_text(
        messages_to_markdown(messages, summary_title=summary_title),
        encoding="utf-8",
    )
    return path.resolve()


def autosave_session(messages: list[dict], live_filename: str) -> Path:
    return save_messages(messages, live_filename)
