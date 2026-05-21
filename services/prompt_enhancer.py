"""
프롬프트 보강 서비스 — 사용자 메시지를 분석하여 시스템 프롬프트를 강화.

워크플로:
1. 사용자 메시지에서 작업 의도(intent) 감지
2. 선택된 페르소나의 시스템 프롬프트 로드
3. 파일 컨텍스트 추가 (첨부 파일 정보)
4. 의도별 task_hint 추가
5. 강화된 시스템 프롬프트 + 정제된 사용자 메시지 반환
"""
from __future__ import annotations

from typing import Optional

from services.persona_service import get_persona


INTENT_KEYWORDS: dict[str, list[str]] = {
    "FILE_META":  ["범위", "라인", "line", "컬럼", "column", "입력된", "채워", "비어있지",
                    "갯수", "개수", "for each", "each file", "per file", "파일별", "각 파일",
                    "파일 마다", "개별 파일"],
    "MERGE":      ["합치", "병합", "통합", "merge", "combine", "합쳐", "묶어"],
    "ANALYSIS":   ["분석", "analyze", "analysis", "패턴", "트렌드", "통계", "집행률"],
    "COMPARISON": ["비교", "compare", "차이", "versus", "vs", "대비"],
    "SUMMARY":    ["요약", "summarize", "summary", "정리", "핵심", "개요"],
    "FILTER":     ["필터", "filter", "조건", "where", "찾아", "검색", "추출", "상위", "하위"],
    "CHART":      ["차트", "그래프", "시각화", "chart", "graph", "plot", "그려"],
}

_INTENT_LABELS: dict[str, str] = {
    "FILE_META": "파일별 구조/범위",
    "MERGE": "파일 병합",
    "ANALYSIS": "데이터 분석",
    "COMPARISON": "비교 분석",
    "SUMMARY": "요약 정리",
    "FILTER": "데이터 필터링",
    "CHART": "시각화",
    "GENERAL": "일반 질문",
}


_MERGE_KEYWORDS = ("합치", "병합", "통합", "merge", "combine", "합쳐", "묶어", "concat")
_PER_FILE_KEYWORDS = (
    "for each file", "each file", "per file", "파일별", "각 파일",
    "파일 마다", "파일마다", "개별 파일", "개별적으로",
)


def _asks_merge(msg_lower: str) -> bool:
    return any(kw in msg_lower for kw in _MERGE_KEYWORDS)


def _asks_per_file(msg_lower: str, original: str) -> bool:
    if any(kw in msg_lower for kw in _PER_FILE_KEYWORDS):
        return True
    return "파일별" in original or "각 파일" in original


def detect_intent(user_message: str) -> str:
    """사용자 메시지에서 작업 의도를 감지합니다."""
    msg_lower = user_message.lower()

    # 파일별·범위 질문은 병합 키워드가 없으면 MERGE/ANALYSIS보다 우선
    if _asks_per_file(msg_lower, user_message) and not _asks_merge(msg_lower):
        meta_score = sum(1 for kw in INTENT_KEYWORDS["FILE_META"] if kw in msg_lower)
        if meta_score >= 1 or "for each" in msg_lower:
            return "FILE_META"

    scores: dict[str, int] = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        if intent == "FILE_META":
            continue
        score = sum(1 for kw in keywords if kw in msg_lower)
        if score > 0:
            scores[intent] = score

    if not scores:
        return "GENERAL"
    return max(scores, key=scores.get)  # type: ignore[arg-type]


def build_file_context(files_metadata: list[dict]) -> str:
    """첨부된 파일 정보를 컨텍스트 문자열로 변환합니다."""
    if not files_metadata:
        return ""

    lines = [f"첨부파일 {len(files_metadata)}개:"]
    for i, meta in enumerate(files_metadata, 1):
        name = meta.get("name", meta.get("original_name", f"file_{i}"))
        rows = meta.get("rows", "?")
        cols = meta.get("cols", "?")
        columns = meta.get("columns", [])
        col_str = f", 컬럼: {columns[:8]}" if columns else ""
        lines.append(f"{i}. {name} (행: {rows}, 열: {cols}{col_str})")

    return "\n".join(lines)


def enhance(
    user_message: str,
    persona_id: str,
    files_metadata: Optional[list[dict]] = None,
    custom_system_prompt: Optional[str] = None,
) -> dict:
    """
    사용자 프롬프트를 보강하여 강화된 시스템 프롬프트를 생성합니다.

    Returns:
        {
            "enhanced_system_prompt": str,
            "refined_user_message": str,
            "detected_intent": str,
            "enhancement_log": str,
        }
    """
    persona = get_persona(persona_id)
    intent = detect_intent(user_message)

    # 시스템 프롬프트 조립
    if custom_system_prompt and custom_system_prompt.strip():
        base_prompt = custom_system_prompt.strip()
        prompt_source = "사용자 지정"
    else:
        base_prompt = persona.system_prompt
        prompt_source = persona.name

    parts = [base_prompt]

    # 파일 컨텍스트 추가
    file_ctx = build_file_context(files_metadata or [])
    if file_ctx:
        parts.append(f"\n[첨부 데이터]\n{file_ctx}")

    # 의도별 힌트 추가
    hint = persona.task_hints.get(intent, "")
    if hint:
        parts.append(f"\n[작업 지침]\n{hint}")

    enhanced_system_prompt = "\n".join(parts)

    # 사용자 메시지 정제 (원본 유지, 앞뒤 공백만 제거)
    refined_user_message = user_message.strip()

    # 보강 로그
    intent_label = _INTENT_LABELS.get(intent, intent)
    log_parts = [f"페르소나: {persona.emoji} {prompt_source}"]
    log_parts.append(f"의도: {intent_label}")
    if file_ctx:
        log_parts.append(f"파일 {len(files_metadata or [])}개 컨텍스트 추가")
    if hint:
        log_parts.append("작업 힌트 적용")
    enhancement_log = " | ".join(log_parts)

    return {
        "enhanced_system_prompt": enhanced_system_prompt,
        "refined_user_message": refined_user_message,
        "detected_intent": intent,
        "enhancement_log": enhancement_log,
    }
