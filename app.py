"""Main entry point: persistent navigation for all tools."""
import streamlit as st
from ui import apply_global_ui
from navigation import PAGE_GROUPS

st.set_page_config(page_title="SEO Audit Suite V6.1", page_icon="◈", layout="wide", initial_sidebar_state="expanded")
apply_global_ui()
pages = {
    group: [st.Page(path, title=title, default=path == "overview.py") for path, title in entries]
    for group, entries in PAGE_GROUPS.items()
}
selected = st.navigation(pages, position="sidebar", expanded=True)
with st.sidebar:
    st.caption("24 audit tools · Scroll the menu to see all pages")
selected.run()
