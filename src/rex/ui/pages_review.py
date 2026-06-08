"""Review page — HITL inbox for low-confidence + unsorted items.

Streamlit page implementing the locked HITL UX:
  - Pick output folder (or auto-detect last scan)
  - Show pending count
  - Card view: one item at a time, pick domain / trash / skip
  - Decisions persist for learning loop
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from rex.projects.context_store import ContextStore
from rex.ui.review_queue import apply_decision, scan_pending

__all__ = ["page_review"]


def _resolve_output() -> Path | None:
    """Resolve the output folder to triage — session > input."""
    default = st.session_state.get("review_output_path", "")
    output = st.text_input(
        "Output folder to review",
        value=default or str(Path("~/rex-data/test-run-1").expanduser()),
        help="Point at the root of a Rex scan (the folder with INDEX.md).",
    )
    if not output:
        return None
    path = Path(output).expanduser()
    if not path.exists():
        st.error(f"Folder not found: `{path}`")
        return None
    st.session_state["review_output_path"] = str(path)
    return path


def _render_card(item, domains: list[str], output_root: Path) -> None:
    """Render one pending-item card and handle user choice."""
    st.markdown(f"#### 📄 `{item.filename}`")
    cols = st.columns([2, 1, 1])
    cols[0].caption(f"Reason: **{item.reason}** · Type bucket: **{item.bucket_hint}**")
    cols[1].caption(f"Size: {item.path.stat().st_size:,} bytes")
    cols[2].caption(f"Path: `{item.path.relative_to(output_root)}`")

    st.write("**Move to which domain?**")
    btn_cols = st.columns(min(len(domains), 4) or 1)
    chosen = None
    for i, d in enumerate(domains):
        if btn_cols[i % len(btn_cols)].button(d, key=f"d_{item.path}_{d}"):
            chosen = d

    new_cat = st.text_input(
        "Or pick a new domain:", key=f"new_{item.path}", placeholder="e.g., R&D",
    )
    extra_cols = st.columns([1, 1, 1])
    if extra_cols[0].button("✅ Move to new", key=f"newgo_{item.path}") and new_cat:
        chosen = new_cat.strip()
    trash = extra_cols[1].button("🗑️ Trash", key=f"trash_{item.path}")
    skip = extra_cols[2].button("⏭️ Skip", key=f"skip_{item.path}")

    if chosen:
        new_path = apply_decision(item, output_root, chosen)
        st.success(f"Moved → `{new_path.relative_to(output_root) if new_path else 'removed'}`")
        st.rerun()
    elif trash:
        apply_decision(item, output_root, None, action="trash")
        st.warning(f"Trashed `{item.filename}`")
        st.rerun()
    elif skip:
        st.info("Skipped — try again next time you open Review.")


def _ensure_domains(output_root: Path) -> list[str]:
    """Resolve the domain list — from project context, else infer from folders."""
    store = ContextStore()
    ctx = store.get_for_project()
    if ctx and ctx.domains:
        return ctx.domains
    return sorted(
        p.name for p in output_root.iterdir()
        if p.is_dir() and not p.name.startswith("_")
    )


def page_review() -> None:
    """Review page entry point — HITL triage for low-conf + unsorted items."""
    st.title("📥 Review — HITL Inbox")
    st.write(
        "Files that Rex was unsure about. Triage them so the next scan learns "
        "from your decisions."
    )

    output_root = _resolve_output()
    if output_root is None:
        return

    items = scan_pending(output_root)
    if not items:
        st.success("🎉 Inbox is clear. No pending items in this scan.")
        return

    st.markdown(
        f"**Pending: {len(items)}** "
        f"({sum(1 for i in items if i.reason == '_Review')} low-conf · "
        f"{sum(1 for i in items if i.reason == '_Unsorted')} no-domain)"
    )

    domains = _ensure_domains(output_root)
    if not domains:
        st.error("No domains found. Run **Onboard** first to declare your domains.")
        return

    idx = st.number_input(
        "Card", min_value=1, max_value=len(items), value=1, step=1,
    ) - 1
    st.markdown("---")
    _render_card(items[idx], domains, output_root)
    st.markdown("---")
    st.caption(f"Card {idx + 1} of {len(items)}")
