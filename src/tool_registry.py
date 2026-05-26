"""
도구 이름 ↔ 실제 함수 매핑 및 Persona별 실행.
"""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from src.excel_actions import suggest_actions
from src.excel_analyzer import analyze_files

# tool_name -> (설명, 실행 함수)
ToolFn = Callable[..., dict[str, Any]]


def _tool_dataframe_summary(
    filenames: list[str],
    frames: dict[str, pd.DataFrame],
    **_: Any,
) -> dict[str, Any]:
    summaries = []
    for i, fname in enumerate(filenames):
        df = frames.get(f"df_{i}")
        if df is None:
            continue
        summaries.append({
            "filename": fname,
            "shape": {"rows": len(df), "cols": len(df.columns)},
            "columns": [str(c) for c in df.columns[:15]],
            "dtypes": {str(c): str(df[c].dtype) for c in df.columns[:10]},
        })
    return {"tool": "dataframe_summary", "files": summaries}


def _tool_statistics_analyzer(
    filenames: list[str],
    frames: dict[str, pd.DataFrame],
    **_: Any,
) -> dict[str, Any]:
    stats = []
    for i, fname in enumerate(filenames):
        df = frames.get(f"df_{i}")
        if df is None:
            continue
        num = df.select_dtypes(include="number")
        desc_summary: dict[str, Any] = {}
        if not num.empty and len(num.columns) > 0:
            col0 = str(num.columns[0])
            s = num[col0].describe()
            desc_summary[col0] = {
                k: float(v) if isinstance(v, (int, float)) else v
                for k, v in s.items()
            }
        stats.append({
            "filename": fname,
            "numeric_columns": [str(c) for c in num.columns[:10]],
            "describe_sample": desc_summary,
            "null_counts_top": {
                str(k): int(v)
                for k, v in df.isna().sum().sort_values(ascending=False).head(5).items()
            },
        })
    return {"tool": "statistics_analyzer", "files": stats}


def _find_column(df: pd.DataFrame, candidates: tuple[str, ...], *, exclude: tuple[str, ...] = ()) -> str | None:
    for cand in candidates:
        for c in df.columns:
            cs = str(c)
            if cand in cs and not any(ex in cs for ex in exclude):
                return cs
    return None


def _tool_kpi_summary(
    filenames: list[str],
    frames: dict[str, pd.DataFrame],
    user_prompt: str = "",
    **_: Any,
) -> dict[str, Any]:
    """예산·집행 관련 컬럼이 있으면 KPI 후보 요약."""
    kpis = []
    for i, fname in enumerate(filenames):
        df = frames.get(f"df_{i}")
        if df is None:
            continue
        plan = _find_column(df, ("계획예산",))
        exec_col = _find_column(
            df,
            ("당해집행", "집행계", "집행액"),
            exclude=("전년", "계획", "예산"),
        )
        entry: dict[str, Any] = {"filename": fname, "kpi_candidates": []}
        if plan and exec_col:
            entry["kpi_candidates"].append(
                f"집행률 후보: {plan} vs {exec_col} (집행률 % 산출 가능)"
            )
        entry["row_count"] = len(df)
        kpis.append(entry)
    return {"tool": "kpi_summary", "files": kpis, "prompt_hint": user_prompt[:200]}


def _tool_insight_generator(
    filenames: list[str],
    frames: dict[str, pd.DataFrame],
    prior_tools: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    prior = prior_tools or {}
    insights = []
    if "kpi_summary" in prior:
        for f in prior["kpi_summary"].get("files", []):
            if f.get("kpi_candidates"):
                insights.append(f"{f['filename']}: " + "; ".join(f["kpi_candidates"]))
    if "statistics_analyzer" in prior:
        insights.append("수치 컬럼 기술통계를 바탕으로 이상값·분산 검토 권장")
    if not insights:
        insights.append("핵심 지표 3~5개를 정의한 뒤 비교표로 의사결정 포인트를 정리하세요")
    return {"tool": "insight_generator", "insights": insights}


def _tool_report_generator(
    filenames: list[str],
    frames: dict[str, pd.DataFrame],
    user_prompt: str = "",
    prior_tools: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    return {
        "tool": "report_generator",
        "purpose": user_prompt[:300] or "사용자 요청 분석",
        "data_sources": filenames,
        "method_notes": [
            "pandas 기반 재현 가능 분석",
            "첨부 파일은 read_excel_smart 로드 기준",
        ],
        "prior_snapshot": list((prior_tools or {}).keys()),
    }


def _tool_methodology_checker(
    filenames: list[str],
    frames: dict[str, pd.DataFrame],
    **_: Any,
) -> dict[str, Any]:
    checks = []
    for i, fname in enumerate(filenames):
        df = frames.get(f"df_{i}")
        if df is None:
            checks.append({"filename": fname, "issue": "데이터 없음"})
            continue
        n = len(df)
        checks.append({
            "filename": fname,
            "sample_size": n,
            "limitation": "표본 수가 작으면( n<30 ) 통계 일반화에 한계" if n < 30 else "표본 크기 양호",
            "missing_rate_pct": round(float(df.isna().sum().sum() / max(df.size, 1) * 100), 1),
        })
    return {"tool": "methodology_checker", "checks": checks}


def _tool_basic_chat(**_: Any) -> dict[str, Any]:
    return {"tool": "basic_chat", "note": "일반 대화 — 구조화된 요약·다음 단계 중심"}


TOOL_REGISTRY: dict[str, tuple[str, ToolFn]] = {
    "excel_analyzer": ("엑셀 구조·used range", lambda **kw: analyze_files(kw["filenames"], kw["frames"])),
    "excel_actions": (
        "엑셀 후속 처리 제안",
        lambda **kw: suggest_actions(kw.get("excel_analyzer") or analyze_files(kw["filenames"], kw["frames"])),
    ),
    "dataframe_summary": ("DataFrame 구조 요약", _tool_dataframe_summary),
    "statistics_analyzer": ("기술통계·결측", _tool_statistics_analyzer),
    "kpi_summary": ("KPI 후보", _tool_kpi_summary),
    "insight_generator": ("경영 인사이트", _tool_insight_generator),
    "report_generator": ("보고서 골격", _tool_report_generator),
    "methodology_checker": ("방법·한계 점검", _tool_methodology_checker),
    "basic_chat": ("기본 대화", _tool_basic_chat),
}


def persona_allowed_tools(persona_tool_names: list[str]) -> list[str]:
    """Persona tools 필드 중 레지스트리에 있는 것만."""
    allowed = []
    for name in persona_tool_names:
        if name in TOOL_REGISTRY:
            allowed.append(name)
        # 레거시 별칭
        elif name == "pandas":
            allowed.append("dataframe_summary")
        elif name == "excel":
            allowed.append("excel_analyzer")
        elif name == "chart":
            allowed.append("dataframe_summary")
        elif name == "statistics":
            allowed.append("statistics_analyzer")
        elif name == "kpi":
            allowed.append("kpi_summary")
    return list(dict.fromkeys(allowed))


def run_tools(
    tool_names: list[str],
    *,
    filenames: list[str],
    frames: dict[str, pd.DataFrame],
    user_prompt: str = "",
) -> dict[str, Any]:
    """도구를 순서대로 실행하고 결과 dict 반환."""
    results: dict[str, Any] = {}
    for name in tool_names:
        if name not in TOOL_REGISTRY:
            continue
        _, fn = TOOL_REGISTRY[name]
        kwargs: dict[str, Any] = {
            "filenames": filenames,
            "frames": frames,
            "user_prompt": user_prompt,
            "prior_tools": results,
        }
        if name == "excel_actions":
            kwargs["excel_analyzer"] = results.get("excel_analyzer")
        try:
            results[name] = fn(**kwargs)
        except Exception as exc:  # noqa: BLE001
            results[name] = {"tool": name, "error": str(exc)}
    return results
