"""Misc pages — job history, semantic search, settings."""

from __future__ import annotations

import asyncio

import streamlit as st

from rex.config import get_settings
from rex.ui.state import get_store


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
