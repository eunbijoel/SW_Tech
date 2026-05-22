"""Ollama 응답 파싱 — thinking, 토큰, 실행 시간."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional


_THINKING_TAG = re.compile(
    r"<(?:think|redacted_thinking)>.*?</(?:think|redacted_thinking)>",
    re.DOTALL | re.IGNORECASE,
)


@dataclass
class OllamaCallResult:
    content: str
    thinking: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    elapsed_ms: float = 0.0
    model: str = ""

    def usage_summary(self) -> str:
        return (
            f"토큰 prompt {self.prompt_tokens:,} · completion {self.completion_tokens:,} "
            f"(합계 {self.total_tokens:,}) · {self.elapsed_ms:.0f}ms"
        )


def split_thinking_from_content(text: str) -> tuple[str, str]:
    """본문과 thinking 블록 분리."""
    if not text:
        return "", ""
    thinking_parts: list[str] = []
    for m in _THINKING_TAG.finditer(text):
        inner = re.sub(r"</?[^>]+>", "", m.group(0)).strip()
        if inner:
            thinking_parts.append(inner)
    visible = _THINKING_TAG.sub("", text).strip()
    return visible, "\n\n".join(thinking_parts)


def parse_ollama_json(data: dict[str, Any], *, wall_elapsed_ms: float, model: str = "") -> OllamaCallResult:
    message = data.get("message") or {}
    raw_content = message.get("content") or data.get("response") or ""
    raw_thinking = message.get("thinking") or ""
    visible, embedded_thinking = split_thinking_from_content(raw_content)
    thinking = raw_thinking.strip() or embedded_thinking
    prompt_t = int(data.get("prompt_eval_count") or 0)
    completion_t = int(data.get("eval_count") or 0)
    total_ns = data.get("total_duration") or 0
    api_ms = float(total_ns) / 1_000_000 if total_ns else 0.0
    elapsed = api_ms if api_ms > 0 else wall_elapsed_ms
    return OllamaCallResult(
        content=visible,
        thinking=thinking,
        prompt_tokens=prompt_t,
        completion_tokens=completion_t,
        total_tokens=prompt_t + completion_t,
        elapsed_ms=elapsed,
        model=model or str(data.get("model") or ""),
    )


def empty_trace_step(label: str, detail: str = "") -> dict[str, str]:
    return {"label": label, "detail": detail}


def iter_ollama_chat_stream(
    *,
    base_url: str,
    model: str,
    messages: list[dict],
    options: dict[str, Any],
    keep_alive: str,
    timeout: int = 600,
) -> Iterator[dict[str, Any]]:
    """Ollama /api/chat stream=True 이벤트 yield."""
    import requests

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "keep_alive": keep_alive,
        "options": options,
    }
    with requests.post(
        f"{base_url.rstrip('/')}/api/chat",
        json=payload,
        stream=True,
        timeout=timeout,
    ) as resp:
        if resp.status_code != 200:
            try:
                err = resp.json().get("error", resp.text)
            except Exception:
                err = resp.text
            raise RuntimeError(f"Ollama 오류 ({resp.status_code}): {err}")
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue


def consume_ollama_stream(
    chunks: Iterator[dict[str, Any]],
    *,
    on_token: Optional[Callable[[str, str], None]] = None,
    wall_elapsed_ms: float = 0,
    model: str = "",
) -> OllamaCallResult:
    """스트림 청크를 합쳐 OllamaCallResult 반환. on_token(role, text) — role: thinking|content."""
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    last: dict[str, Any] = {}
    for data in chunks:
        last = data
        msg = data.get("message") or {}
        if msg.get("thinking"):
            thinking_parts.append(msg["thinking"])
            if on_token:
                on_token("thinking", msg["thinking"])
        if msg.get("content"):
            content_parts.append(msg["content"])
            if on_token:
                on_token("content", msg["content"])
        if data.get("done"):
            break
    raw_content = "".join(content_parts)
    raw_thinking = "".join(thinking_parts)
    if last:
        merged = dict(last)
        merged.setdefault("message", {})
        merged["message"] = {
            **(merged.get("message") or {}),
            "content": raw_content,
            "thinking": raw_thinking,
        }
        return parse_ollama_json(merged, wall_elapsed_ms=wall_elapsed_ms, model=model)
    visible, embedded = split_thinking_from_content(raw_content)
    thinking = raw_thinking.strip() or embedded
    return OllamaCallResult(
        content=visible,
        thinking=thinking,
        elapsed_ms=wall_elapsed_ms,
        model=model,
    )
