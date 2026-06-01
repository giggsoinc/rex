"""Streamlit UI for Rex — Phase 1.

Run: streamlit run src/rex/ui/app.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import streamlit as st

from rex.config import get_settings
from rex.orchestrator.builder import build_default_pipeline
from rex.orchestrator.state import JobStore

st.set_page_config(
    page_title="Rex — Data Cleanup",
    page_icon="📁",
    layout="wide",
    initial_sidebar_state="expanded",
)


def get_store() -> JobStore:
    """Cached job store."""
    if "job_store" not in st.session_state:
        st.session_state.job_store = JobStore(base_path="~/rex-data/jobs")
    return st.session_state.job_store


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


def page_jobs() -> None:
    """Job history."""
    st.title("📊 Jobs")
    store = get_store()
    jobs = asyncio.run(store.list_jobs())

    if not jobs:
        st.info("No scans yet. Run one from the Scan page.")
        return

    for job in jobs:
        with st.expander(f"{job.name} — {job.status.value} — {job.scanned_files} files"):
            cols = st.columns(4)
            cols[0].metric("Scanned", job.scanned_files)
            cols[1].metric("Classified", job.classified_files)
            cols[2].metric("Organized", job.organized_files)
            cols[3].metric("Duplicates", job.duplicate_count)

            st.caption(f"Source: `{job.source_path}`")
            st.caption(f"Output: `{job.output_path}`")
            st.caption(f"Created: {job.created_at}")
            if job.categories_discovered:
                st.write("**Categories:** " + ", ".join(job.categories_discovered))


def page_browse() -> None:
    """Browse organized output."""
    st.title("🗂️ Browse")
    store = get_store()
    jobs = asyncio.run(store.list_jobs())

    if not jobs:
        st.info("No scans yet.")
        return

    job_options = {f"{j.name} ({j.id[:12]})": j.id for j in jobs}
    selected = st.selectbox("Select job", options=list(job_options.keys()))
    job_id = job_options[selected]

    files = asyncio.run(store.list_files(job_id))
    decisions = asyncio.run(store.list_decisions(job_id))

    if not files:
        st.warning("No files found for this job.")
        return

    # Filter by category
    categories = sorted({decisions[fid].category for fid in decisions if fid in decisions})
    cat_filter = st.multiselect("Filter by category", options=categories, default=categories)

    rows = []
    for f in files:
        d = decisions.get(f.id)
        if d is None:
            continue
        if cat_filter and d.category not in cat_filter:
            continue
        rows.append({
            "filename": f.filename,
            "category": d.category,
            "tags": ", ".join(d.tags),
            "relevance": d.relevance,
            "action": d.action.value,
            "dedup": d.dedup_status.value,
            "size_kb": round(f.size_bytes / 1024, 1),
            "media": f.media_type.value,
        })

    st.dataframe(rows, use_container_width=True, hide_index=True)

    # Selected file detail
    filenames = [r["filename"] for r in rows]
    if filenames:
        chosen = st.selectbox("Inspect file", options=[""] + filenames)
        if chosen:
            file_obj = next((f for f in files if f.filename == chosen), None)
            if file_obj:
                d = decisions.get(file_obj.id)
                st.subheader(file_obj.filename)
                st.json({
                    "category": d.category if d else None,
                    "tags": d.tags if d else [],
                    "relevance": d.relevance if d else None,
                    "action": d.action.value if d else None,
                    "reasoning": d.reasoning if d else None,
                    "dedup_status": d.dedup_status.value if d else None,
                    "duplicate_of": d.duplicate_of if d else None,
                    "original_path": file_obj.original_path,
                    "sha256": file_obj.sha256_hash,
                })
                if file_obj.extracted_text:
                    st.text_area("Extracted text preview", file_obj.extracted_text[:2000], height=200)
                if file_obj.image_description:
                    st.text_area("Image description", file_obj.image_description, height=120)


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


def page_settings() -> None:
    """Settings — read-only display of current config."""
    st.title("⚙️ Settings")
    s = get_settings()
    st.subheader("Active configuration")
    st.json({
        "deployment_mode": s.deployment_mode.value,
        "llm_provider": s.llm_provider.value,
        "llm_model": s.llm_model,
        "embed_model": s.embed_model,
        "vector_store": s.vector_store.value,
        "vector_path": s.vector_path,
        "vision_provider": s.vision_provider.value,
        "vision_model": s.vision_model,
        "secret_provider": s.secret_provider,
        "storage_path": s.storage_path,
        "dedup_near_threshold": s.dedup_near_threshold,
        "dedup_related_threshold": s.dedup_related_threshold,
    })
    st.info("To change settings, edit `.env.local` or rerun `rex init`.")


PAGES = {
    "📁 Scan": page_scan,
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
