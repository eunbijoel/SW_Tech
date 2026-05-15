"""
Unit tests for ExcelService (no AI calls — sandbox and code extraction only).
"""
import pandas as pd
import pytest

from backend.services.excel_service import ExcelService


@pytest.fixture
def svc() -> ExcelService:
    return ExcelService()


def test_describe_schemas(svc: ExcelService) -> None:
    frames = {
        "df_0": pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}),
        "df_1": pd.DataFrame({"c": [3.0]}),
    }
    desc = svc._describe_schemas(frames)
    assert "df_0" in desc
    assert "df_1" in desc
    assert "2 rows" in desc
    assert "1 rows" in desc


def test_extract_code_with_fences(svc: ExcelService) -> None:
    raw = "Here is the code:\n```python\nresult = df_0.head(5)\n```\nDone."
    code = svc._extract_code(raw)
    assert code == "result = df_0.head(5)"


def test_extract_code_no_fences(svc: ExcelService) -> None:
    raw = "result = df_0.head(5)"
    code = svc._extract_code(raw)
    assert code == "result = df_0.head(5)"


def test_execute_code_head(svc: ExcelService) -> None:
    frames = {"df_0": pd.DataFrame({"x": range(10)})}
    code = "result = df_0.head(3)"
    df, err = svc._execute_code(code, frames)
    assert err is None
    assert df is not None
    assert len(df) == 3


def test_execute_code_concat(svc: ExcelService) -> None:
    df1 = pd.DataFrame({"id": [1, 2], "v": [10, 20]})
    df2 = pd.DataFrame({"id": [3, 4], "v": [30, 40]})
    frames = {"df_0": df1, "df_1": df2}
    code = "result = pd.concat([df_0, df_1], ignore_index=True)"
    df, err = svc._execute_code(code, frames)
    assert err is None
    assert df is not None
    assert len(df) == 4


def test_execute_code_bad_code(svc: ExcelService) -> None:
    frames = {"df_0": pd.DataFrame({"x": [1]})}
    code = "result = undefined_var.head()"
    df, err = svc._execute_code(code, frames)
    assert df is None
    assert err is not None


def test_execute_code_no_result(svc: ExcelService) -> None:
    frames = {"df_0": pd.DataFrame({"x": [1]})}
    code = "x = 42"  # no `result` variable
    df, err = svc._execute_code(code, frames)
    assert df is None
    assert err is not None
