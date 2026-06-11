"""Browse page — inspect organized output for a job."""

from __future__ import annotations

import asyncio

import streamlit as st

from rex.ui.state import get_all_jobs


def page_browse() -> None:
    """Browse organized output."""
    st.title("🗂️ Browse")
    job_pairs = get_all_jobs()

    if not job_pairs:
        st.info("No scans yet.")
        return

    job_options = {f"{j.name} ({j.id[:12]})": (j.id, s) for j, s in job_pairs}
    selected = st.selectbox("Select job", options=list(job_options.keys()))
    job_id, store = job_options[selected]

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
