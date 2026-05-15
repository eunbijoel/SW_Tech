"""
Streamlit session state management helpers.
Centralises default values so pages don't have conflicting initialisations.
"""
import uuid
import streamlit as st


def init_session() -> None:
    """Call once at the top of every page."""
    defaults: dict = {
        "session_id": str(uuid.uuid4()),
        "messages": [],          # Chat history [{role, content}]
        "selected_model": "",    # Currently chosen model string
        "selected_files": [],    # File IDs selected for Excel processing
        "api_key": "",           # Backend API key (debug: leave empty)
        "executor": "local",     # "local" | "gpu" | "spark"
        "theme": "light",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def add_message(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})


def clear_messages() -> None:
    st.session_state.messages = []


def set_model(model: str) -> None:
    st.session_state.selected_model = model


def get_model() -> str:
    return st.session_state.get("selected_model", "")


def set_selected_files(file_ids: list[str]) -> None:
    st.session_state.selected_files = file_ids


def get_selected_files() -> list[str]:
    return st.session_state.get("selected_files", [])
