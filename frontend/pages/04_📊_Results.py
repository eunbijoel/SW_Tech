"""
Results page — browse, preview, and manage saved AI outputs.

Features:
  - Tab: Markdown results → preview with rendered markdown
  - Tab: Excel results → metadata + download button
  - Delete button on each result
  - Refresh button
"""
import streamlit as st

from frontend.utils.api_client import (
    delete_result,
    get_markdown_result,
    list_results,
)
from frontend.utils.session import init_session

st.set_page_config(page_title="Results · AI Prompt Platform", page_icon="📊", layout="wide")
init_session()

st.title("📊 Saved Results")

col_title, col_refresh = st.columns([5, 1])
with col_refresh:
    if st.button("Refresh", use_container_width=True):
        st.rerun()

try:
    results = list_results(result_type="all")
except Exception as e:
    st.error(f"Could not load results: {e}")
    results = {"markdown": [], "excel": []}

md_results = results.get("markdown", [])
xl_results = results.get("excel", [])

tab_md, tab_xl = st.tabs([
    f"Markdown ({len(md_results)})",
    f"Excel ({len(xl_results)})",
])

# ── Markdown results ──────────────────────────────────────────────────────────
with tab_md:
    if not md_results:
        st.info("No markdown results saved yet. Run a chat with 'Save response' enabled.")
    else:
        col_list, col_preview = st.columns([1, 2])

        with col_list:
            st.caption("Select a file to preview")
            for item in md_results:
                fname: str = item["filename"]
                size: float = item["size_kb"]
                modified: str = item["modified"][:10]

                with st.container():
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        if st.button(
                            f"📄 {fname[:35]}",
                            key=f"md_open_{fname}",
                            help=f"{size} KB · {modified}",
                            use_container_width=True,
                        ):
                            st.session_state["preview_md"] = fname
                    with c2:
                        if st.button("🗑️", key=f"md_del_{fname}", help="Delete"):
                            try:
                                if delete_result("markdown", fname):
                                    st.success(f"Deleted {fname}")
                                    if st.session_state.get("preview_md") == fname:
                                        del st.session_state["preview_md"]
                                    st.rerun()
                            except Exception as e:
                                st.error(str(e))

        with col_preview:
            preview_file: str | None = st.session_state.get("preview_md")
            if preview_file:
                st.caption(f"Previewing: `{preview_file}`")
                try:
                    content = get_markdown_result(preview_file)
                    st.markdown(content)
                except Exception as e:
                    st.error(f"Could not load preview: {e}")
            else:
                st.info("Click a file on the left to preview it here.")

# ── Excel results ─────────────────────────────────────────────────────────────
with tab_xl:
    if not xl_results:
        st.info("No Excel results saved yet. Process files on the Files page.")
    else:
        for item in xl_results:
            fname = item["filename"]
            size = item["size_kb"]
            modified = item["modified"][:16].replace("T", " ")

            with st.container():
                col_info, col_dl, col_del = st.columns([4, 1, 1])
                with col_info:
                    st.markdown(f"**{fname}**  \n{size} KB · {modified}")
                with col_dl:
                    # Direct download via backend URL
                    dl_url = f"http://localhost:8000/api/v1/files/results/excel/{fname}"
                    st.link_button("Download", dl_url, use_container_width=True)
                with col_del:
                    if st.button("🗑️", key=f"xl_del_{fname}", help="Delete"):
                        try:
                            if delete_result("excel", fname):
                                st.success(f"Deleted {fname}")
                                st.rerun()
                        except Exception as e:
                            st.error(str(e))

                st.divider()
