"""persona_router 전략 결정 테스트."""
from src.persona_manager import load_persona_profile
from src.persona_router import decide_strategy


def test_excel_expert_range_uses_tool_response():
    profile = load_persona_profile("excel_expert")
    strategy = decide_strategy(
        profile,
        "FILE_META",
        "각 파일에서 문자가 입력된 행 열 범위를 알려줘",
        has_attachments=True,
    )
    assert strategy.execution_path == "tool_response"
    assert "excel_analyzer" in strategy.tools_to_run


def test_chart_uses_llm_codegen():
    profile = load_persona_profile("data_analyst")
    strategy = decide_strategy(
        profile,
        "CHART",
        "비목별 집행률 막대 차트를 그려줘",
        has_attachments=True,
    )
    assert strategy.execution_path == "llm_codegen"
