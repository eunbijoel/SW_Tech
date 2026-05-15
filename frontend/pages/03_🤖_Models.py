"""
Models page — provider health, model listing, Ollama model management.

Features:
  - Provider health cards (OpenAI / Gemini / Ollama)
  - Available models per provider in expandable sections
  - Ollama model pull (with streaming status updates)
  - Ollama model delete
"""
import streamlit as st

from frontend.utils.api_client import (
    delete_ollama_model,
    list_models,
    models_health,
    pull_ollama_model,
)
from frontend.utils.session import init_session

st.set_page_config(page_title="Models · AI Prompt Platform", page_icon="🤖", layout="wide")
init_session()

st.title("🤖 AI Models")

# ── Provider Health ───────────────────────────────────────────────────────────
st.subheader("Provider Status")

try:
    health = models_health()
    col1, col2, col3 = st.columns(3)

    def _health_card(col, name: str, ok: bool, icon: str) -> None:
        with col:
            status = "Online" if ok else "Offline"
            color = "green" if ok else "red"
            st.markdown(
                f"""
                <div style="border:1px solid {'#28a745' if ok else '#dc3545'};
                            border-radius:8px; padding:16px; text-align:center;">
                  <div style="font-size:2rem">{icon}</div>
                  <div style="font-weight:bold; font-size:1.1rem">{name}</div>
                  <div style="color:{'#28a745' if ok else '#dc3545'}; font-weight:bold">{status}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    _health_card(col1, "OpenAI", health.get("openai", False), "🟢")
    _health_card(col2, "Google Gemini", health.get("gemini", False), "🔵")
    _health_card(col3, "Ollama (local)", health.get("ollama", False), "🟡")

except Exception as e:
    st.warning(f"Could not fetch provider health: {e}")

st.divider()

# ── Available Models ──────────────────────────────────────────────────────────
st.subheader("Available Models")

try:
    model_map = list_models()
except Exception as e:
    st.error(f"Could not load models: {e}")
    model_map = {}

provider_icons = {"openai": "🟢", "gemini": "🔵", "ollama": "🟡"}
provider_labels = {"openai": "OpenAI (GPT)", "gemini": "Google Gemini", "ollama": "Ollama (local)"}

for provider in ["openai", "gemini", "ollama"]:
    names = model_map.get(provider, [])
    icon = provider_icons[provider]
    label = provider_labels[provider]
    with st.expander(f"{icon} {label} — {len(names)} model(s)", expanded=(provider == "ollama")):
        if names:
            for name in names:
                st.markdown(f"- `{name}`")
        else:
            if provider == "ollama":
                st.info("No Ollama models installed yet. Pull one below.")
            else:
                st.info("No models found. Check your API key configuration.")

st.divider()

# ── Ollama Model Management ───────────────────────────────────────────────────
st.subheader("Ollama Model Management")

tab_pull, tab_delete = st.tabs(["Pull / Download", "Delete"])

with tab_pull:
    st.markdown("Download a new model from the [Ollama library](https://ollama.com/library).")
    col_input, col_btn = st.columns([4, 1])
    model_name = col_input.text_input(
        "Model name",
        placeholder="e.g. llama3, mistral, phi3, codellama:13b",
        label_visibility="collapsed",
    )
    pull_clicked = col_btn.button("Pull", type="primary", use_container_width=True)

    if pull_clicked and model_name.strip():
        progress_box = st.empty()
        status_lines: list[str] = []
        with st.spinner(f"Pulling `{model_name}`… (this may take several minutes)"):
            try:
                resp = pull_ollama_model(model_name.strip())
                # The pull endpoint returns a streaming response; read lines
                for line in resp.iter_lines():
                    if line and line != "[DONE]":
                        status_lines.append(line)
                        progress_box.code("\n".join(status_lines[-15:]))
                st.success(f"`{model_name}` pulled successfully. Refresh the page to see it.")
            except Exception as e:
                st.error(f"Pull failed: {e}")
    elif pull_clicked:
        st.warning("Enter a model name first.")

with tab_delete:
    ollama_models = model_map.get("ollama", [])
    if not ollama_models:
        st.info("No Ollama models installed.")
    else:
        st.warning("Deleting a model is irreversible. You will need to re-pull it.")
        model_to_delete = st.selectbox("Select model to delete", ollama_models)
        if st.button("Delete model", type="secondary"):
            try:
                ok = delete_ollama_model(model_to_delete)
                if ok:
                    st.success(f"Deleted `{model_to_delete}`.")
                    st.rerun()
                else:
                    st.error(f"Failed to delete `{model_to_delete}`.")
            except Exception as e:
                st.error(f"Error: {e}")
