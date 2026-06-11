"""Shared UI state helpers for the Rex Streamlit app.

Jobs live in TWO kinds of stores: the global ~/rex-data/jobs and each
project's own jobs_path. Every page must aggregate across all of them —
a single-store view silently hides project scans ("No scans yet" bug).
"""

from __future__ import annotations

import asyncio

import streamlit as st

from rex.cli.tail import _all_stores
from rex.orchestrator.state import JobStore


def get_store() -> JobStore:
    """Cached global job store (legacy single-store accessor)."""
    if "job_store" not in st.session_state:
        st.session_state.job_store = JobStore(base_path="~/rex-data/jobs")
    return st.session_state.job_store


def get_all_jobs() -> list[tuple[object, JobStore]]:
    """Every job across global + per-project stores, with its owning store.

    Sorted newest-first by created_at. Deduplicates by job id (a job id is
    deterministic per source folder, so the same id can't live in two
    stores with different content we'd care about).
    """
    async def collect() -> list[tuple[object, JobStore]]:
        seen: set[str] = set()
        out: list[tuple[object, JobStore]] = []
        for store in _all_stores():
            for job in await store.list_jobs():
                if job.id not in seen:
                    seen.add(job.id)
                    out.append((job, store))
        return out

    jobs = asyncio.run(collect())
    jobs.sort(key=lambda t: getattr(t[0], "created_at", None) or 0, reverse=True)
    return jobs


def default_output_path() -> str:
    """First project's output path — sane default for the Review page."""
    from rex.projects.store import ProjectStore
    for project in ProjectStore().list_all():
        if project.output_path:
            return project.output_path
    return ""
