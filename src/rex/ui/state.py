"""Shared UI state helpers for the Rex Streamlit app."""

from __future__ import annotations

import streamlit as st

from rex.orchestrator.state import JobStore


def get_store() -> JobStore:
    """Cached job store."""
    if "job_store" not in st.session_state:
        st.session_state.job_store = JobStore(base_path="~/rex-data/jobs")
    return st.session_state.job_store
