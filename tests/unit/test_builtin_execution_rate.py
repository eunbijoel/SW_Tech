import pandas as pd

from app import try_builtin_execution_rate_table


def test_chart_request_not_builtin_table():
    import pandas as pd

    from app import try_builtin_execution_rate_table

    frames = {"df_0": pd.DataFrame({"계획예산": [100], "합계": [50]})}
    out = try_builtin_execution_rate_table(
        "계획예산 대비 집행계의 집행률(%)을 그래프로 보여주세요",
        ["a.xlsx"],
        frames,
    )
    assert out is None


def test_builtin_execution_rate():
    frames = {
        "df_0": pd.DataFrame({
            "비목분류": ["인건비"],
            "계획예산": [100],
            "합계": [50],
        }),
    }
    out = try_builtin_execution_rate_table(
        "계획예산 대비 집행계의 집행률(%)을 표로 보여주세요",
        ["a.xlsx"],
        frames,
    )
    assert out is not None
    assert "집행률(%)" in out["dataframe"].columns
    assert out["dataframe"]["집행률(%)"].iloc[0] == 50.0
