"""Reusable file management UI component."""
import streamlit as st
from frontend.utils import api_client


def render_file_table(files: list[dict], show_select: bool = False) -> list[str]:
    """
    Render uploaded files as a table.
    Returns list of selected file IDs if show_select=True.
    """
    selected: list[str] = []
    if not files:
        st.info("No files uploaded yet.")
        return selected

    for f in files:
        col1, col2, col3, col4, col5 = st.columns([0.5, 3, 1.5, 1.5, 1])
        with col1:
            if show_select:
                checked = st.checkbox("", key=f"sel_{f['id']}", label_visibility="collapsed")
                if checked:
                    selected.append(f["id"])
        with col2:
            st.write(f"📄 **{f['original_name']}**")
        with col3:
            kb = f["size_bytes"] / 1024
            st.write(f"{kb:.1f} KB")
        with col4:
            st.write(f['uploaded_at'][:10])
        with col5:
            if st.button("🗑️", key=f"del_{f['id']}", help="Delete this file"):
                if api_client.delete_file(f["id"]):
                    st.success(f"Deleted {f['original_name']}")
                    st.rerun()

    return selected


def render_upload_zone(session_id: str = "") -> list[dict]:
    """Drag-and-drop upload widget. Returns list of newly uploaded file records."""
    uploaded = st.file_uploader(
        "Upload Excel / CSV files",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        help="Max 100 MB per file. Multiple files allowed.",
    )
    if uploaded and st.button("⬆️ Upload files", type="primary"):
        file_bytes = [(f.name, f.read()) for f in uploaded]
        with st.spinner("Uploading..."):
            try:
                records = api_client.upload_files(file_bytes, session_id=session_id)
                st.success(f"Uploaded {len(records)} file(s) successfully.")
                return records
            except Exception as e:
                st.error(f"Upload failed: {e}")
    return []
