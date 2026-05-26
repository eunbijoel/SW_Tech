"""
엑셀/데이터프레임 실제 분석 — used range, 구조, 결측 등.

LLM 없이 디스크·메모리의 DataFrame 으로 계산합니다.
"""
from __future__ import annotations

from typing import Any

import pandas as pd


def _used_range_bounds(df: pd.DataFrame) -> dict[str, Any]:
    """비어 있지 않은 셀 기준 사용 범위 (pandas 로드 기준)."""
    if df.empty:
        return {
            "rows": 0,
            "cols": 0,
            "filled_cells": 0,
            "range_a1": "—",
            "empty_row_gaps": 0,
            "missing_column_names": 0,
        }

    # object 포함 모든 값에서 비어 있지 않은 위치
    mask = df.notna() & (df.astype(str).replace({"nan": "", "None": ""}) != "")
    if not mask.any().any():
        return {
            "rows": len(df),
            "cols": len(df.columns),
            "filled_cells": 0,
            "range_a1": "—",
            "empty_row_gaps": 0,
            "missing_column_names": sum(1 for c in df.columns if str(c).startswith("Unnamed")),
        }

    true_rows = [i for i in range(len(df)) if mask.iloc[i].any()]
    true_cols = [j for j in range(len(df.columns)) if mask.iloc[:, j].any()]
    if not true_rows or not true_cols:
        r0, r1, c0, c1 = 0, len(df) - 1, 0, len(df.columns) - 1
    else:
        r0, r1 = min(true_rows), max(true_rows)
        c0, c1 = min(true_cols), max(true_cols)

    filled = int(mask.iloc[r0 : r1 + 1, c0 : c1 + 1].sum().sum())
    used_rows = r1 - r0 + 1
    used_cols = c1 - c0 + 1

    def col_letter(n: int) -> str:
        s = ""
        n += 1
        while n:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s

    range_a1 = f"{col_letter(c0)}{r0 + 1}:{col_letter(c1)}{r1 + 1}"

    # 연속 블록 안의 완전 빈 행 개수
    empty_gaps = 0
    for ri in range(r0, r1 + 1):
        if not mask.iloc[ri, c0 : c1 + 1].any():
            empty_gaps += 1

    missing_names = sum(1 for c in df.columns if str(c).startswith("Unnamed"))

    return {
        "rows": used_rows,
        "cols": used_cols,
        "filled_cells": filled,
        "range_a1": range_a1,
        "empty_row_gaps": empty_gaps,
        "missing_column_names": missing_names,
        "full_shape": {"rows": len(df), "cols": len(df.columns)},
    }


def analyze_file(
    filename: str,
    df: pd.DataFrame,
    *,
    sheet_label: str = "Sheet1",
) -> dict[str, Any]:
    """단일 파일 분석 결과."""
    bounds = _used_range_bounds(df)
    dtypes = {str(c): str(df[c].dtype) for c in df.columns[:20]}
    null_pct = float(df.isna().sum().sum() / max(df.size, 1) * 100)

    return {
        "filename": filename,
        "sheet": sheet_label,
        "used_range": bounds,
        "columns_sample": [str(c) for c in list(df.columns)[:12]],
        "dtypes_sample": dtypes,
        "null_pct": round(null_pct, 1),
        "duplicate_rows": int(df.duplicated().sum()),
    }


def analyze_files(
    filenames: list[str],
    frames: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """여러 첨부 파일 일괄 분석."""
    files: list[dict[str, Any]] = []
    for i, fname in enumerate(filenames):
        var = f"df_{i}"
        df = frames.get(var)
        if df is None:
            files.append({"filename": fname, "error": "DataFrame 없음"})
            continue
        files.append(analyze_file(fname, df))

    return {
        "tool": "excel_analyzer",
        "file_count": len(files),
        "files": files,
    }
