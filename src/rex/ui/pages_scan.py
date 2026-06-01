"""Scan page — point Rex at a folder and run the pipeline."""

from __future__ import annotations

import asyncio
from pathlib import Path

import streamlit as st

from rex.orchestrator.builder import build_default_pipeline


def page_scan() -> None:
    """Scan page — point at a folder, run pipeline."""
    st.title("📁 Scan")
    st.write("Point Rex at a folder. It will scan, classify, dedupe, and organize.")

    folder = st.text_input("Folder path", value=str(Path.home() / "Downloads"))
    output = st.text_input(
        "Output path",
        value=str(Path.home() / "rex-data" / "output"),
        help="Where Rex will write organized output (it will not modify your source folder)",
    )
    name = st.text_input("Job name (optional)", value="")

    if st.button("Start scan", type="primary"):
        src = Path(folder).expanduser()
        if not src.exists() or not src.is_dir():
            st.error(f"Folder not found: {src}")
            return

        progress_bar = st.progress(0, text="Initializing…")
        status_box = st.empty()
        stats_cols = st.columns(5)

        async def run():
            pipeline = build_default_pipeline()

            async def on_progress(p):
                total = max(p.total, 1)
                done = max(p.organized, p.routed, p.scanned)
                progress_bar.progress(min(done / total, 1.0), text=f"{p.status.value} · {p.current_file[:60]}")
                with stats_cols[0]:
                    st.metric("Total", p.total)
                with stats_cols[1]:
                    st.metric("Scanned", p.scanned)
                with stats_cols[2]:
                    st.metric("Routed", p.routed)
                with stats_cols[3]:
                    st.metric("Organized", p.organized)
                with stats_cols[4]:
                    st.metric("Duplicates", p.duplicates)

            pipeline.on_progress = on_progress
            return await pipeline.run(str(src), output_path=output, name=name)

        try:
            job = asyncio.run(run())
            status_box.success(f"Done! Job {job.id} — {job.organized_files} files organized.")
            st.session_state.last_job_id = job.id
        except Exception as e:
            status_box.error(f"Pipeline failed: {e}")
