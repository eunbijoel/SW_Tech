from services.chat_catalog import (
    chat_fingerprint,
    dedupe_chat_items,
    summarize_prompt_title,
)


def test_summarize_merge_prompt():
    t = "첨부된 모든 엑셀 파일을 하나로 병합하고, 계획예산 대비 집행계의 집행률(%)을 계산해주세요."
    assert summarize_prompt_title(t) == "파일 병합"


def test_summarize_structure_prompt():
    t = "df_0, df_1, df_2에 각각 출처 컬럼을 추가해 pd.concat으로 통합하세요."
    assert summarize_prompt_title(t) == "다중 파일 통합"


def test_dedupe_keeps_newest():
    from datetime import datetime

    older = {
        "name": "a.md",
        "mtime": datetime(2026, 5, 22, 16, 0),
        "fingerprint": "abc",
    }
    newer = {
        "name": "b.md",
        "mtime": datetime(2026, 5, 22, 16, 27),
        "fingerprint": "abc",
    }
    out = dedupe_chat_items([older, newer])
    assert len(out) == 1
    assert out[0]["name"] == "b.md"


def test_fingerprint_stable():
    p = "첨부된 모든 엑셀 파일을 병합"
    assert chat_fingerprint(first_prompt=p) == chat_fingerprint(first_prompt=p + "  ")
