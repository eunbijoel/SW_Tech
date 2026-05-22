"""services/prompt_enhancer.py 단위 테스트."""
import pytest

from services.prompt_enhancer import (
    detect_intent,
    build_file_context,
    enhance,
)


class TestDetectIntent:
    """의도 감지 테스트."""

    @pytest.mark.parametrize(
        "msg, expected",
        [
            ("5개 파일을 합쳐주세요", "MERGE"),
            ("파일 병합해줘", "MERGE"),
            ("merge these files", "MERGE"),
            ("예산 집행률을 분석해주세요", "ANALYSIS"),
            ("데이터 패턴을 찾아주세요", "ANALYSIS"),
            ("전년도와 비교해주세요", "COMPARISON"),
            ("4차 vs 5차 대비", "COMPARISON"),
            ("핵심 내용을 요약해줘", "SUMMARY"),
            ("잔액 상위 5개 추출해주세요", "FILTER"),
            ("조건에 맞는 행을 찾아주세요", "FILTER"),
            ("차트를 그려주세요", "CHART"),
            ("그래프 시각화", "CHART"),
            (
                "엑셀 파일에서 문자가 입력된 범위 (라인, 컬럼) 의 갯수를 알아내줘. for each file",
                "FILE_META",
            ),
            ("각 파일별로 행 열 범위만 알려줘", "FILE_META"),
            ("안녕하세요", "GENERAL"),
            ("오늘 날씨 어때?", "GENERAL"),
        ],
    )
    def test_intent_detection(self, msg: str, expected: str):
        assert detect_intent(msg) == expected

    def test_empty_message_returns_general(self):
        assert detect_intent("") == "GENERAL"


class TestBuildFileContext:
    """파일 컨텍스트 생성 테스트."""

    def test_no_files_returns_empty(self):
        assert build_file_context([]) == ""

    def test_single_file(self):
        meta = [{"name": "sales.xlsx", "rows": 100, "cols": 5}]
        ctx = build_file_context(meta)
        assert "첨부파일 1개" in ctx
        assert "sales.xlsx" in ctx
        assert "행: 100" in ctx

    def test_multiple_files(self):
        meta = [
            {"name": "a.xlsx", "rows": 10, "cols": 3},
            {"name": "b.csv", "rows": 20, "cols": 4},
        ]
        ctx = build_file_context(meta)
        assert "첨부파일 2개" in ctx
        assert "a.xlsx" in ctx
        assert "b.csv" in ctx

    def test_with_columns(self):
        meta = [{"name": "t.xlsx", "rows": 5, "cols": 2, "columns": ["A", "B"]}]
        ctx = build_file_context(meta)
        assert "컬럼" in ctx

    def test_missing_fields_uses_defaults(self):
        meta = [{"original_name": "fallback.xlsx"}]
        ctx = build_file_context(meta)
        assert "fallback.xlsx" in ctx


class TestEnhance:
    """프롬프트 보강 통합 테스트."""

    def test_returns_all_required_keys(self):
        result = enhance("파일을 분석해주세요", "data_analyst")
        assert "enhanced_system_prompt" in result
        assert "refined_user_message" in result
        assert "detected_intent" in result
        assert "enhancement_log" in result
        assert "enhanced_prompt" in result

    def test_persona_applied(self):
        result = enhance("분석해줘", "data_analyst")
        assert "수석 데이터 분석가" in result["enhanced_system_prompt"]

    def test_general_persona_fallback(self):
        result = enhance("안녕", "unknown_id")
        assert "AI 어시스턴트" in result["enhanced_system_prompt"]

    def test_file_context_included(self):
        meta = [{"name": "test.xlsx", "rows": 10, "cols": 3}]
        result = enhance("분석해줘", "general", files_metadata=meta)
        assert "[Attached Data]" in result["enhanced_system_prompt"]
        assert "test.xlsx" in result["enhanced_system_prompt"]

    def test_no_files_no_context(self):
        result = enhance("분석해줘", "general", files_metadata=[])
        assert "[Attached Data]" not in result["enhanced_system_prompt"]

    def test_task_hint_applied(self):
        result = enhance("파일 3개를 병합해주세요", "data_analyst")
        assert result["detected_intent"] == "MERGE"
        assert "[Task Hint · MERGE]" in result["enhanced_system_prompt"]

    def test_custom_system_prompt_overrides(self):
        custom = "나는 커스텀 프롬프트입니다."
        result = enhance("분석해줘", "data_analyst", custom_system_prompt=custom)
        assert custom in result["enhanced_system_prompt"]
        assert "[System Instruction]" in result["enhanced_system_prompt"]
        assert "사용자 지정" in result["enhancement_log"]

    def test_refined_message_trimmed(self):
        result = enhance("  공백 있는 메시지  ", "general")
        assert result["refined_user_message"] == "공백 있는 메시지"

    def test_enhancement_log_format(self):
        result = enhance("분석해줘", "excel_expert")
        log = result["enhancement_log"]
        assert "📋" in log
        assert "엑셀 전문가" in log
