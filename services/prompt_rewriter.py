"""
LLM 기반 프롬프트 리라이터 — Ollama로 페르소나 관점 프롬프트 재작성.

기존 sections_to_preview_text()의 기계적 텍스트 결합 대신,
LLM이 페르소나의 전문성을 자연스럽게 녹여낸 프롬프트를 생성.
실패 시 기존 방식(fallback)으로 안전하게 폴백.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

from services.ollama_trace import OllamaCallResult, parse_ollama_json

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

REWRITE_OPTS: dict[str, Any] = {
    "num_predict": 256,
    "num_ctx": 2048,
    "temperature": 0.4,
}

REWRITE_TIMEOUT_SEC = 60

_META_SYSTEM_PROMPT = """\
당신은 프롬프트 리라이터입니다.
사용자의 원래 요청을 AI 페르소나의 전문성을 녹여 하나의 자연스러운 프롬프트로 재작성합니다.

규칙:
1. 사용자의 원래 의도를 절대 변경하지 마세요
2. 페르소나의 분석 관점과 전문 용어를 자연스럽게 반영하세요
3. [section_name] 같은 라벨이나 === 같은 구분선 없이 자연스러운 문장으로 작성하세요
4. 한국어로 간결하게 작성하세요
5. 리라이트된 프롬프트 텍스트만 출력하세요 — 설명, 인사말, 따옴표 없이
"""


@dataclass
class RewriteResult:
    """프롬프트 리라이트 결과."""
    rewritten_prompt: str
    original_preview: str
    used_llm: bool
    ollama_result: OllamaCallResult | None = None
    error: str = ""


def _build_meta_prompt(sections: dict[str, str]) -> list[dict[str, str]]:
    """리라이트용 system + user 메시지 — 핵심 정보만 간결하게."""
    parts: list[str] = []

    persona = sections.get("persona_role", "").strip()
    if persona:
        parts.append(f"페르소나: {persona}")

    focus = sections.get("analysis_focus", "").strip()
    if focus:
        parts.append(f"분석 관점: {focus}")

    hint = sections.get("task_hint", "").strip()
    if hint:
        parts.append(f"작업 힌트: {hint}")

    intent = sections.get("detected_intent", "").strip()
    if intent:
        parts.append(f"의도: {intent}")

    file_ctx = sections.get("file_context", "").strip()
    if file_ctx:
        file_lines = file_ctx.split("\n")[:4]
        parts.append(f"파일: {'; '.join(file_lines)}")

    user_request = sections.get("user_request", "").strip()
    parts.append(f"\n사용자 요청: {user_request}")
    parts.append("\n위 정보를 바탕으로 사용자 요청을 페르소나 관점에서 하나의 자연스러운 프롬프트로 리라이트해주세요.")

    return [
        {"role": "system", "content": _META_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(parts)},
    ]


def _make_fallback(fallback_text: str, error: str = "") -> RewriteResult:
    return RewriteResult(
        rewritten_prompt=fallback_text,
        original_preview=fallback_text,
        used_llm=False,
        error=error,
    )


def rewrite_prompt(
    sections: dict[str, str],
    *,
    model: str,
    fallback_text: str,
) -> RewriteResult:
    """
    Ollama LLM을 호출하여 프롬프트를 페르소나 관점으로 재작성.

    실패 시 fallback_text(기존 섹션 결합 방식)를 반환.
    """
    if not model:
        return _make_fallback(fallback_text, "모델 미선택")

    messages = _build_meta_prompt(sections)
    user_request = sections.get("user_request", "")

    logger.info("Prompt rewrite: model=%s, request='%s'", model, user_request[:50])

    try:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": REWRITE_OPTS,
        }
        t0 = time.perf_counter()
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=REWRITE_TIMEOUT_SEC,
        )
        wall_ms = (time.perf_counter() - t0) * 1000
        logger.info("Prompt rewrite: completed in %.0fms, status=%s", wall_ms, r.status_code)

        if r.status_code != 200:
            try:
                err_detail = r.json().get("error", r.text)
            except Exception:
                err_detail = r.text
            logger.warning("Prompt rewrite Ollama error %s: %s", r.status_code, err_detail)
            return _make_fallback(fallback_text, f"Ollama 오류 ({r.status_code})")

        result = parse_ollama_json(r.json(), wall_elapsed_ms=wall_ms, model=model)
        rewritten = result.content.strip()

        logger.info("Prompt rewrite result (%d chars): %s", len(rewritten), rewritten[:80])

        if not rewritten or (user_request and len(rewritten) < len(user_request) * 0.3):
            logger.warning("Rewrite result too short (%d chars), using fallback", len(rewritten))
            return RewriteResult(
                rewritten_prompt=fallback_text,
                original_preview=fallback_text,
                used_llm=False,
                ollama_result=result,
                error="리라이트 결과 부적절 (너무 짧음)",
            )

        return RewriteResult(
            rewritten_prompt=rewritten,
            original_preview=fallback_text,
            used_llm=True,
            ollama_result=result,
        )

    except requests.ConnectionError:
        logger.warning("Prompt rewrite: Ollama connection failed")
        return _make_fallback(fallback_text, "Ollama 연결 실패")
    except (requests.Timeout, requests.exceptions.ReadTimeout):
        logger.warning("Prompt rewrite: Ollama timeout (%ds)", REWRITE_TIMEOUT_SEC)
        return _make_fallback(fallback_text, "리라이트 시간 초과")
    except Exception as exc:
        logger.exception("Prompt rewrite unexpected error")
        return _make_fallback(fallback_text, str(exc))
