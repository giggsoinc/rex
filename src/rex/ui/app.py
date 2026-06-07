"""Streamlit UI for Rex — Phase 1.

Run: streamlit run src/rex/ui/app.py
"""

from __future__ import annotations

import streamlit as st

from rex.ui.pages_browse import page_browse
from rex.ui.pages_misc import page_jobs, page_search, page_settings
from rex.ui.pages_onboard import page_onboard
from rex.ui.pages_review import page_review
from rex.ui.pages_scan import page_scan
from rex.ui.state import get_store

st.set_page_config(
    page_title="Rex — Data Cleanup",
    page_icon="📁",
    layout="wide",
    initial_sidebar_state="expanded",
)


PAGES = {
    "🚀 Onboard": page_onboard,
    "📁 Scan": page_scan,
    "📥 Review": page_review,
    "📊 Jobs": page_jobs,
    "🗂️ Browse": page_browse,
    "🔎 Search": page_search,
    "⚙️ Settings": page_settings,
}


def main() -> None:
    """Streamlit entry point."""
    st.sidebar.title("Rex")
    st.sidebar.caption("Data Cleanup & Knowledge Management")
    selection = st.sidebar.radio("Navigation", list(PAGES.keys()))
    PAGES[selection]()
    st.sidebar.markdown("---")
    st.sidebar.caption("Phase 1 · Local mode · LanceDB + qwen3:8b")


main()
