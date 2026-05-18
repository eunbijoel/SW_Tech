"""
Chat page — redirects to the main app (app.py is now the chat interface).
This page is kept so the sidebar nav link doesn't 404.
"""
import streamlit as st

st.set_page_config(page_title="Chat · Basic Software Technology", page_icon="💬")

st.info("💬 채팅은 메인 화면에서 바로 이용할 수 있습니다.")
st.page_link("frontend/app.py", label="🏠 메인 채팅으로 이동", icon="↩")
