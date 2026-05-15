"""Reusable chat message rendering component."""
import streamlit as st


def render_chat_history(messages: list[dict]) -> None:
    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])


def render_model_badge(model: str, provider: str) -> None:
    color = {"openai": "🟢", "gemini": "🔵", "ollama": "🟡"}.get(provider, "⚪")
    st.caption(f"{color} `{model}` via **{provider}**")


def token_usage_bar(input_tokens: int, output_tokens: int) -> None:
    col1, col2 = st.columns(2)
    col1.metric("Input tokens", f"{input_tokens:,}")
    col2.metric("Output tokens", f"{output_tokens:,}")
