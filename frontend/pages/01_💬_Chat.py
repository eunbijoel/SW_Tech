"""
Chat page — interactive AI chat with model/executor selection.

Features:
  - Model picker grouped by provider (sidebar)
  - Executor selector: local / GPU / Spark (sidebar)
  - Save-result toggle with optional title (sidebar)
  - Full chat history rendered with st.chat_message()
  - Token usage displayed after each assistant turn
  - Clear chat button
"""
import streamlit as st

from frontend.components.chat import render_chat_history, render_model_badge, token_usage_bar
from frontend.utils.api_client import chat_complete, list_models, models_health
from frontend.utils.session import add_message, clear_messages, get_model, init_session, set_model

st.set_page_config(page_title="Chat · AI Prompt Platform", page_icon="💬", layout="wide")
init_session()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Chat Settings")

    # Model selection
    with st.spinner("Loading models..."):
        try:
            model_map = list_models()
        except Exception:
            model_map = {"openai": [], "gemini": [], "ollama": []}

    all_models: list[str] = []
    for provider, names in model_map.items():
        for name in names:
            all_models.append(f"{name}")

    if not all_models:
        all_models = ["gpt-4o", "gemini-1.5-pro", "llama3"]

    current_model = get_model() or all_models[0]
    if current_model not in all_models:
        all_models.insert(0, current_model)

    selected_model = st.selectbox(
        "Model",
        options=all_models,
        index=all_models.index(current_model),
        help="Select an AI model. Prefix determines provider: gpt-* → OpenAI, gemini-* → Gemini, others → Ollama",
    )
    set_model(selected_model)

    st.divider()

    # Provider health
    st.caption("Provider Health")
    try:
        health = models_health()
        cols = st.columns(3)
        cols[0].metric("OpenAI", "OK" if health.get("openai") else "Down")
        cols[1].metric("Gemini", "OK" if health.get("gemini") else "Down")
        cols[2].metric("Ollama", "OK" if health.get("ollama") else "Down")
    except Exception:
        st.caption("(health check unavailable)")

    st.divider()

    # Generation parameters
    temperature = st.slider("Temperature", 0.0, 2.0, 0.2, 0.05)
    max_tokens = st.number_input("Max tokens", 256, 32768, 4096, 256)

    st.divider()

    # Save result toggle
    save_result = st.toggle("Save response as Markdown", value=False)
    result_title = ""
    if save_result:
        result_title = st.text_input("Result title (optional)", placeholder="My analysis")

    st.divider()
    if st.button("Clear chat", use_container_width=True):
        clear_messages()
        st.rerun()

# ── Main area ─────────────────────────────────────────────────────────────────
st.title("💬 AI Chat")

messages: list[dict] = st.session_state.get("messages", [])
render_chat_history(messages)

# Chat input is always shown at the bottom
if prompt := st.chat_input("Ask anything…"):
    add_message("user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                resp = chat_complete(
                    messages=st.session_state.messages,
                    model=selected_model,
                    temperature=temperature,
                    max_tokens=int(max_tokens),
                    save_result=save_result,
                    result_title=result_title,
                )
                content: str = resp["content"]
                provider: str = resp.get("provider", "")
                model_used: str = resp.get("model", selected_model)
                input_tok: int = resp.get("input_tokens", 0)
                output_tok: int = resp.get("output_tokens", 0)
                saved_path: str | None = resp.get("saved_path")

                st.markdown(content)
                render_model_badge(model_used, provider)

                add_message("assistant", content)

                if input_tok or output_tok:
                    with st.expander("Token usage", expanded=False):
                        token_usage_bar(input_tok, output_tok)

                if saved_path:
                    st.success(f"Saved to `{saved_path}`")

            except Exception as e:
                err = f"Error: {e}"
                st.error(err)
                add_message("assistant", err)
