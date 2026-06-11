"""Scan page — submit a background scan (same detach path as `rex scan`).

The pipeline never runs inside the Streamlit process: submission spawns a
detached child, shows a toast, and progress lives on the 📊 Jobs page.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from rex.projects.context_store import ContextStore
from rex.projects.store import ProjectStore


def page_scan() -> None:
    """Submit a scan to the background and point at the Jobs page."""
    st.title("📁 Scan")
    st.write(
        "Point Rex at a folder. The scan runs in the **background** — "
        "follow it on the 📊 Jobs page, kill it anytime."
    )

    projects = ProjectStore().list_all()
    if not projects:
        st.error("No projects yet — create one first: `rex project create <name>` "
                 "or use 🚀 Onboard.")
        return
    proj_by_name = {p.name: p for p in projects}
    proj_name = st.selectbox("Project", options=list(proj_by_name))
    project = proj_by_name[proj_name]

    folder = st.text_input("Folder to scan", value=str(Path.home() / "Downloads"))
    output = st.text_input(
        "Output path (blank = project default)", value=project.output_path or "",
        help="Overrides the project's output path for this run.",
    )
    workers = st.slider("Workers", min_value=1, max_value=8, value=4)

    # Show whether SortEngine will be active (BusinessContext present)
    ctx = ContextStore().get_for_project(project.root_path) or ContextStore().get_for_project()
    if ctx and ctx.domains:
        st.info(f"🎯 SortEngine active — domains: **{', '.join(ctx.domains)}**.")
    else:
        st.warning("⚠️ No BusinessContext — legacy type-only folders. Visit 🚀 Onboard.")

    if st.button("🚀 Submit scan", type="primary"):
        src = Path(folder).expanduser()
        if not src.exists() or not src.is_dir():
            st.error(f"Folder not found: {src}")
            return
        from rex.cli.scan_submit import submit_background
        out_override = output.strip() or None
        if out_override == project.output_path:
            out_override = None
        rc = submit_background(
            src.resolve(), project, workers=workers, mode="asyncio",
            soft=True, output_override=out_override,
        )
        if rc != 0:
            st.warning(
                "⚠️ A scan for this folder is **already running** — follow it "
                "on the 📊 Jobs page, or kill it there first."
            )
            return
        st.toast(f"Scan submitted for {project.name} — running in background.", icon="🚀")
        st.success(
            "🚀 **Scan submitted.** Track stage, ETA, and kill it from the "
            "**📊 Jobs** page (left sidebar). Don't shut the machine down "
            "until it completes. Re-running a finished folder is safe — "
            "already-scanned files are skipped (hash idempotency)."
        )
