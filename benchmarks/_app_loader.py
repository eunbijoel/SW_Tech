"""Streamlit 없이 app.py 헬퍼만 로드 (벤치마크용)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]


class _SessionState(dict):
    """streamlit.session_state — 속성·키 양쪽 접근."""

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value) -> None:
        self[name] = value


def _mock_columns(spec) -> tuple:
    n = spec if isinstance(spec, int) else len(spec)
    return tuple(MagicMock() for _ in range(n))


def install_streamlit_mock() -> MagicMock:
    if "streamlit" in sys.modules and not isinstance(sys.modules["streamlit"], MagicMock):
        return sys.modules["streamlit"]
    mock_st = MagicMock()
    mock_st.session_state = _SessionState(
        {
            "fast_mode": True,
            "use_enhancement": True,
            "persona_id": "general",
            "messages": [],
            "attached_files": [],
            "selected_model": "",
            "show_persona_form": False,
        }
    )
    mock_st.columns = _mock_columns
    mock_st.sidebar = MagicMock()
    mock_st.chat_message = lambda *a, **k: MagicMock(__enter__=lambda s: s, __exit__=lambda *e: None)
    mock_st.status = lambda *a, **k: MagicMock(__enter__=lambda s: s, __exit__=lambda *e: None)
    mock_st.expander = lambda *a, **k: MagicMock(__enter__=lambda s: s, __exit__=lambda *e: None)
    mock_st.empty = MagicMock
    mock_st.button = lambda *a, **k: False
    mock_st.selectbox = lambda *a, **k: (k.get("options") or [""])[0]
    mock_st.text_input = lambda *a, **k: ""
    mock_st.text_area = lambda *a, **k: ""
    mock_st.checkbox = lambda *a, **k: k.get("value", False)
    sys.modules["streamlit"] = mock_st
    return mock_st


def load_app():
    """app 모듈 로드 (최초 1회)."""
    import os

    os.environ["SW_TECH_BENCHMARK"] = "1"
    install_streamlit_mock()
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    import app as app_module  # noqa: WPS433 — intentional late import

    return app_module
