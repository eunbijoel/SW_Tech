"""
AI Prompt Platform — Streamlit entry point.

Run: streamlit run frontend/app.py
     (from the ai-prompt-platform/ directory)
"""
import streamlit as st
from frontend.utils.session import init_session
from frontend.utils.api_client import backend_health

st.set_page_config(
    page_title="AI Prompt Platform",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_session()

# ── Sidebar — global controls ─────────────────────────────────────────────────
with st.sidebar:
    st.title("🤖 AI Prompt Platform")
    st.divider()

    # Backend health indicator
    healthy = backend_health()
    status_color = "🟢" if healthy else "🔴"
    st.caption(f"{status_color} Backend: {'Online' if healthy else 'Offline'}")

    st.divider()
    st.subheader("Navigation")
    st.page_link("frontend/app.py",              label="🏠 Home")
    st.page_link("frontend/pages/01_💬_Chat.py", label="💬 Chat")
    st.page_link("frontend/pages/02_📁_Files.py",label="📁 Files")
    st.page_link("frontend/pages/03_🤖_Models.py",label="🤖 Models")
    st.page_link("frontend/pages/04_📊_Results.py",label="📊 Results")

    st.divider()
    st.caption("v1.0.0 · AI Prompt Platform")

# ── Home page ─────────────────────────────────────────────────────────────────
st.title("🤖 AI Prompt Platform")
st.markdown("""
Welcome to your **production AI prompt platform**.

Use the navigation on the left to:

| Page | What you can do |
|------|----------------|
| 💬 **Chat** | Interactive AI chat with any model |
| 📁 **Files** | Upload, manage, and process Excel files |
| 🤖 **Models** | Manage AI models, download Ollama models |
| 📊 **Results** | Browse, preview, and download saved results |
""")

st.divider()
col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Backend Status", "Online" if healthy else "Offline")
with col2:
    msg_count = len(st.session_state.get("messages", []))
    st.metric("Chat Messages", msg_count)
with col3:
    file_count = len(st.session_state.get("selected_files", []))
    st.metric("Selected Files", file_count)

if not healthy:
    st.warning(
        "⚠️ Backend is offline. Start it with:\n"
        "```bash\nuvicorn backend.main:app --reload\n```"
    )
