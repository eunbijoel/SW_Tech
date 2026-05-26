"""excel_analyzer used range 테스트."""
import pandas as pd

from src.excel_analyzer import analyze_file, analyze_files


def test_used_range_non_empty():
    df = pd.DataFrame({"A": [1, None, 3], "B": ["x", "", "z"]})
    result = analyze_file("t.xlsx", df)
    ur = result["used_range"]
    assert ur["filled_cells"] >= 4
    assert ur["rows"] >= 2
    assert ur["cols"] >= 1


def test_analyze_files_multiple():
    frames = {
        "df_0": pd.DataFrame({"col": [1, 2]}),
        "df_1": pd.DataFrame({"x": [10]}),
    }
    out = analyze_files(["a.xlsx", "b.xlsx"], frames)
    assert out["file_count"] == 2
