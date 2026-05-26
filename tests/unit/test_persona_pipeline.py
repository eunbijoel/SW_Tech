"""Persona 파이프라인 통합 테스트."""
import pandas as pd

from src.persona_pipeline import prepare_persona_execution


def test_excel_expert_tool_response_markdown():
    frames = {
        "df_0": pd.DataFrame(
            {f"c{j}": [1 if i < 3 else None for i in range(5)] for j in range(4)}
        ),
    }
    plan = prepare_persona_execution(
        "이 파일에서 문자가 입력된 범위가 몇 행 몇 열인지 알려줘",
        "excel_expert",
        filenames=["sample.xlsx"],
        frames=frames,
        files_metadata=[{"name": "sample.xlsx", "rows": 5, "cols": 4}],
    )
    assert plan.execution_path == "tool_response"
    assert plan.tool_formatted_markdown
    assert "### 1." in plan.tool_formatted_markdown
    assert "sample.xlsx" in plan.tool_formatted_markdown
    assert "excel_analyzer" in plan.tool_results
