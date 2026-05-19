"""services/persona_service.py 단위 테스트."""
import pytest

from services.persona_service import (
    PERSONAS,
    Persona,
    get_persona,
    list_personas,
)


class TestPersonas:
    """페르소나 정의 검증."""

    def test_five_personas_exist(self):
        assert len(PERSONAS) == 5

    @pytest.mark.parametrize(
        "pid",
        ["data_analyst", "excel_expert", "business_consultant", "researcher", "general"],
    )
    def test_each_persona_has_required_fields(self, pid: str):
        p = PERSONAS[pid]
        assert isinstance(p, Persona)
        assert p.id == pid
        assert len(p.name) > 0
        assert len(p.emoji) > 0
        assert len(p.description) > 0
        assert len(p.system_prompt) > 20
        assert isinstance(p.task_hints, dict)
        assert len(p.task_hints) >= 1

    def test_get_persona_valid(self):
        p = get_persona("data_analyst")
        assert p.id == "data_analyst"
        assert p.name == "데이터 분석가"

    def test_get_persona_invalid_returns_general(self):
        p = get_persona("nonexistent_id")
        assert p.id == "general"

    def test_get_persona_empty_string_returns_general(self):
        p = get_persona("")
        assert p.id == "general"

    def test_list_personas_returns_all(self):
        result = list_personas()
        assert len(result) == 5
        ids = {p.id for p in result}
        assert ids == {"data_analyst", "excel_expert", "business_consultant", "researcher", "general"}

    def test_all_system_prompts_contain_korean(self):
        for pid, persona in PERSONAS.items():
            has_korean = any("가" <= c <= "힣" for c in persona.system_prompt)
            assert has_korean, f"{pid} system_prompt에 한국어가 없습니다"

    def test_task_hints_include_merge_and_analysis(self):
        for pid, persona in PERSONAS.items():
            assert "MERGE" in persona.task_hints, f"{pid}에 MERGE 힌트 없음"
            assert "ANALYSIS" in persona.task_hints, f"{pid}에 ANALYSIS 힌트 없음"
