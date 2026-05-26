"""
excel_analyzer 결과를 바탕으로 실행 가능한 후속 단계 제안.
"""
from __future__ import annotations

from typing import Any


def suggest_actions(analysis: dict[str, Any]) -> dict[str, Any]:
    """정제·병합 등 실행 제안 목록."""
    suggestions: list[str] = []
    for f in analysis.get("files", []):
        if f.get("error"):
            suggestions.append(f"{f.get('filename')}: 파일을 다시 첨부하세요.")
            continue
        fname = f.get("filename", "file")
        ur = f.get("used_range", {})
        if ur.get("empty_row_gaps", 0) > 0:
            suggestions.append(f"{fname}: 중간 빈 행 {ur['empty_row_gaps']}개 — 제거 또는 채우기 검토")
        if ur.get("missing_column_names", 0) > 0:
            suggestions.append(f"{fname}: Unnamed 컬럼 — 헤더 행 지정·컬럼명 표준화")
        if f.get("null_pct", 0) > 15:
            suggestions.append(f"{fname}: 결측 비율 {f['null_pct']}% — 결측 처리 규칙 정의")
        if f.get("duplicate_rows", 0) > 0:
            suggestions.append(f"{fname}: 중복 행 {f['duplicate_rows']}건 — dedup 여부 확인")

    if len(analysis.get("files", [])) > 1:
        suggestions.append("동일 구조 파일끼리 병합 가능 여부 — 컬럼명·dtype 비교 후 진행")

    if not suggestions:
        suggestions.append("현재 구조로 집계·필터·차트 분석 진행 가능")

    return {
        "tool": "excel_actions",
        "actions": suggestions,
    }
