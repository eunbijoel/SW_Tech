"""
Subprocess-isolated Python code execution sandbox.

The AI-generated pandas code is written to a temp script and executed in a
child process with a configurable timeout.  The child serialises its result
DataFrame as JSON to stdout; the parent deserialises it.  A crash or hang in
the child cannot kill the FastAPI worker.

Usage:
    sandbox = SubprocessSandbox(timeout=60)
    result_df, error = sandbox.run(code, frames)
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pandas as pd

from backend.core.logging import get_logger

log = get_logger(__name__)

SANDBOX_TIMEOUT = 60  # seconds


class SubprocessSandbox:
    """
    Runs AI-generated pandas code in a child process.

    The generated script receives DataFrames serialised as JSON temp files,
    executes user code, then prints the result as JSON to stdout.
    """

    def __init__(self, timeout: int = SANDBOX_TIMEOUT) -> None:
        self._timeout = timeout

    def run(
        self,
        code: str,
        frames: dict[str, pd.DataFrame],
    ) -> tuple[pd.DataFrame | None, str | None]:
        """
        Execute `code` in a subprocess with the provided DataFrames available.

        Returns (result_df, error_string).  On success error_string is None.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            frame_paths: dict[str, str] = {}
            for name, df in frames.items():
                p = tmp / f"{name}.json"
                df.to_json(p, orient="records", force_ascii=False)
                frame_paths[name] = str(p)

            script = self._build_script(code, frame_paths)
            script_path = tmp / "generated.py"
            script_path.write_text(script, encoding="utf-8")

            try:
                proc = subprocess.run(
                    [sys.executable, str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                )
            except subprocess.TimeoutExpired:
                log.warning("Sandbox timeout", timeout=self._timeout)
                return None, f"Execution timed out after {self._timeout}s"

            if proc.returncode != 0:
                error = proc.stderr.strip() or "Unknown execution error"
                log.warning("Sandbox subprocess failed", error=error[:500])
                return None, error

            stdout = proc.stdout.strip()
            if not stdout:
                return None, "Code did not produce a result (stdout empty)"

            try:
                records = json.loads(stdout)
                df = pd.DataFrame(records)
                return df, None
            except Exception as e:
                return None, f"Could not parse result JSON: {e}"

    @staticmethod
    def _build_script(user_code: str, frame_paths: dict[str, str]) -> str:
        """
        Build the full child-process script.
        Loads each DataFrame from its JSON path, executes user code,
        then prints result as JSON.
        """
        load_lines = "\n".join(
            f'    {name} = pd.read_json({path!r}, orient="records")'
            for name, path in frame_paths.items()
        )

        return textwrap.dedent(f"""\
            import json
            import sys
            import pandas as pd
            import numpy as np

            def _main():
            {load_lines or "    pass"}

                # ── user-generated code ──
            {textwrap.indent(user_code, "    ")}
                # ── end user code ──

                result = locals().get("result")
                if result is None:
                    # try global scope
                    result = globals().get("result")

                if isinstance(result, pd.Series):
                    result = result.to_frame()

                if not isinstance(result, pd.DataFrame):
                    print(json.dumps({{"__error__": f"result is {{type(result).__name__}}, expected DataFrame"}}))
                    sys.exit(1)

                print(result.to_json(orient="records", force_ascii=False))

            _main()
        """)
