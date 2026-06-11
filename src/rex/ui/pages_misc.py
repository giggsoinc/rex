"""Misc pages — live-refreshing job history + semantic search."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import streamlit as st

from rex.config import get_settings
from rex.models.schemas import JobStatus
from rex.ui.jobs_actions import eta_text, mark_if_crashed, render_kill_controls
from rex.ui.state import get_store

_STUCK_AFTER = timedelta(minutes=5)  # no heartbeat for 5+ min → stuck


def _live_status(job) -> str:
    """Return human status emoji + label, including stuck detection."""
    if job.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.AWAITING_REVIEW):
        return job.status.value
    hb = job.last_progress_at
    if hb is None:
        return f"{job.status.value} (no heartbeat)"
    # Treat naive timestamps as UTC
    if hb.tzinfo is None:
        hb = hb.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - hb
    if age > _STUCK_AFTER:
        mins = int(age.total_seconds() // 60)
        return f"⚠️ STUCK ({job.status.value} · idle {mins}m)"
    return f"🟢 LIVE — {job.status.value}"


def page_jobs() -> None:
    """Live-refreshing job history (auto-poll every 2s)."""
    st.title("📊 Jobs")
    auto = st.toggle("🔄 Auto-refresh (2s)", value=True, help="Polls job.json on disk")
    show_done = st.toggle("Show completed", value=True)
    if auto:
        # Streamlit-native auto-refresh — re-runs the script every 2 seconds.
        # We use st.empty + sleep rather than st_autorefresh to avoid the extra dep.
        from time import time as _t
        st.caption(f"Last poll: {datetime.now().strftime('%H:%M:%S')}")

    store = get_store()
    jobs = asyncio.run(store.list_jobs())
    if not show_done:
        jobs = [j for j in jobs if j.status != JobStatus.COMPLETE]

    if not jobs:
        st.info("No scans yet. Run one from the Scan page.")
        return

    for job in jobs:
        from rex.cli.jobs import _find_job_dir
        job_dir = _find_job_dir(job.id)
        if job_dir is not None and mark_if_crashed(store, job, job_dir):
            st.toast(f"Job {job.name} marked crashed (process died).", icon="💀")
        label = f"{job.name} — {_live_status(job)} — {job.scanned_files}/{job.total_files}"
        with st.expander(label, expanded=(job.status not in (JobStatus.COMPLETE, JobStatus.FAILED))):
            cols = st.columns(4)
            cols[0].metric("Scanned", job.scanned_files)
            cols[1].metric("Classified", job.classified_files)
            cols[2].metric("Organized", job.organized_files)
            cols[3].metric("Duplicates", job.duplicate_count)

            eta = eta_text(job)
            if eta:
                st.caption(f"⏳ {eta}")
            if job.current_file:
                st.caption(f"📄 Current: `{job.current_file}`")
            if job_dir is not None:
                render_kill_controls(job, job_dir)
            if job.last_progress_at:
                st.caption(f"⏱  Last heartbeat: {job.last_progress_at}")
            st.caption(f"Source: `{job.source_path}`")
            st.caption(f"Output: `{job.output_path}`")
            st.caption(f"Created: {job.created_at}")
            if job.error:
                st.error(job.error)
            if job.categories_discovered:
                st.write("**Categories:** " + ", ".join(job.categories_discovered))

    if auto:
        import time as _time
        _time.sleep(2)
        st.rerun()


def page_search() -> None:
    """Semantic search."""
    st.title("🔎 Search")
    st.write("Semantic search across all scanned files.")

    query = st.text_input("Search", value="", placeholder="e.g., Q3 revenue planning")
    top_k = st.slider("Results", min_value=3, max_value=20, value=10)

    if st.button("Search") and query.strip():
        from rex.ml.provider import ModelProvider
        from rex.vectorstore import get_vector_store

        settings = get_settings()
        model = ModelProvider(settings)
        store = get_vector_store(settings)

        async def do_search():
            await store.initialize()
            vec = await model.embed(query)
            return await store.search(vec, top_k=top_k)

        try:
            matches = asyncio.run(do_search())
        except Exception as e:
            st.error(f"Search failed: {e}")
            return

        if not matches:
            st.info("No results.")
            return

        for m in matches:
            with st.expander(f"{m.metadata.get('filename', m.file_id)} · score={m.similarity_score:.3f}"):
                st.json(m.metadata)


# page_settings moved to pages_settings.py — fully editable + masked secrets.
