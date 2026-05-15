"""
Excel processing service.

Workflow:
1. Load one or more Excel/CSV files into pandas DataFrames.
2. Ask the AI to translate the user's natural-language prompt into a
   pandas code snippet (code-generation approach).
3. Execute the snippet in a restricted local namespace.
4. Return the resulting DataFrame + a human-readable explanation.

Security note:
  The generated code runs in a controlled namespace with only pandas and
  numpy available. Production deployments should wrap this in a subprocess
  or sandbox (e2b, Docker exec, RestrictedPython).
"""
import io
import re
import textwrap
from pathlib import Path

import pandas as pd

from backend.core.logging import get_logger
from backend.services.ai.base import CompletionRequest, Message
from backend.services.ai.router import ai_router
from backend.services.sandbox import SubprocessSandbox

log = get_logger(__name__)


CODE_SYSTEM_PROMPT = textwrap.dedent("""
You are a data engineering assistant.
The user has loaded one or more DataFrames (named df_0, df_1, … df_N).
Each DataFrame corresponds to an uploaded Excel/CSV file.
Your job is to:
1. Write a single Python code block using pandas (and numpy if needed).
2. Store the final result in a variable called `result`.
3. Do NOT import any other libraries.
4. Return ONLY the code block, no explanations.

Example:
```python
result = pd.concat([df_0, df_1]).groupby('id').mean().reset_index()
```
""").strip()

EXPLAIN_SYSTEM_PROMPT = textwrap.dedent("""
You are a helpful data analyst.
Explain what the following pandas operation did in plain English.
Be concise (3-5 sentences).
""").strip()


class ExcelService:
    async def load_files(self, paths: list[Path]) -> dict[str, pd.DataFrame]:
        """Load each file into a named DataFrame (df_0, df_1 …)."""
        frames: dict[str, pd.DataFrame] = {}
        for i, path in enumerate(paths):
            frames[f"df_{i}"] = self._read_file(path)
            log.info("Loaded file", name=f"df_{i}", path=str(path), rows=len(frames[f"df_{i}"]))
        return frames

    def _read_file(self, path: Path) -> pd.DataFrame:
        ext = path.suffix.lower()
        if ext == ".csv":
            return pd.read_csv(path)

        # Try multi-level header first (common in Korean budget tables).
        # If two header rows create a MultiIndex, flatten them to "상위_하위" strings.
        raw = pd.read_excel(path, engine="openpyxl", header=None, nrows=3)
        first_row_merged = raw.iloc[0].isna().sum() > len(raw.columns) * 0.3
        second_row_looks_like_header = (
            raw.shape[0] >= 2
            and raw.iloc[1].apply(lambda v: isinstance(v, str)).sum() >= 3
        )

        if first_row_merged and second_row_looks_like_header:
            df = pd.read_excel(path, engine="openpyxl", header=[0, 1])
            df.columns = [
                "_".join(str(c).strip() for c in col if "Unnamed" not in str(c)).strip("_") or f"col_{i}"
                for i, col in enumerate(df.columns)
            ]
        else:
            df = pd.read_excel(path, engine="openpyxl")

        return df

    async def process(
        self,
        file_paths: list[Path],
        user_prompt: str,
        model: str = "",
    ) -> dict:
        """
        Main entry point.
        Returns {
            "result_df": pd.DataFrame | None,
            "code": str,
            "explanation": str,
            "error": str | None,
        }
        """
        frames = await self.load_files(file_paths)
        schema_description = self._describe_schemas(frames)

        # Step 1 — AI generates pandas code
        code_request = CompletionRequest(
            messages=[
                Message("system", CODE_SYSTEM_PROMPT),
                Message(
                    "user",
                    f"Available DataFrames:\n{schema_description}\n\nUser request: {user_prompt}",
                ),
            ],
            model=model,
            temperature=0.1,
        )
        code_response = await ai_router.complete(code_request)
        code = self._extract_code(code_response.content)
        log.info("Generated pandas code", code=code[:200])

        # Step 2 — Execute in sandbox namespace
        result_df, exec_error = self._execute_code(code, frames)

        # Step 3 — AI explains the result
        explanation = ""
        if result_df is not None and exec_error is None:
            explain_request = CompletionRequest(
                messages=[
                    Message("system", EXPLAIN_SYSTEM_PROMPT),
                    Message("user", f"Code:\n```python\n{code}\n```\nResult shape: {result_df.shape}"),
                ],
                model=model,
                temperature=0.3,
            )
            explanation = (await ai_router.complete(explain_request)).content

        return {
            "result_df": result_df,
            "code": code,
            "explanation": explanation,
            "error": exec_error,
        }

    def _describe_schemas(self, frames: dict[str, pd.DataFrame]) -> str:
        lines = []
        for name, df in frames.items():
            col_info = ", ".join(f"{c} ({df[c].dtype})" for c in df.columns)
            lines.append(f"{name}: {len(df)} rows | columns: [{col_info}]")
        return "\n".join(lines)

    def _extract_code(self, raw: str) -> str:
        match = re.search(r"```(?:python)?\n(.*?)```", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        return raw.strip()

    def _execute_code(
        self, code: str, frames: dict[str, pd.DataFrame]
    ) -> tuple[pd.DataFrame | None, str | None]:
        sandbox = SubprocessSandbox(timeout=60)
        return sandbox.run(code, frames)

    def dataframe_to_bytes(self, df: pd.DataFrame, fmt: str = "xlsx") -> bytes:
        """Serialize a DataFrame to bytes (xlsx or csv)."""
        buf = io.BytesIO()
        if fmt == "csv":
            df.to_csv(buf, index=False, encoding="utf-8-sig")
        else:
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df.to_excel(writer, index=False)
        return buf.getvalue()


excel_service = ExcelService()
