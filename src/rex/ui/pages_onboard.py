"""Onboarding wizard — capture BusinessContext at first scan.

Streamlit page implementing the three-question wizard:
  Q1: What's this folder about? (one sentence)
  Q2: Key domains you care about? (multi-select + custom)
  Q3: Confidence threshold (low / medium / high)

Plus model-profile picker: Local / Balanced / Premium / Custom.

Persists via ContextStore — both per-project (.raven/business_context.json)
and per-job (~/rex-data/contexts/{job_id}.json).
"""

from __future__ import annotations

import streamlit as st

from rex.models.business_context import BusinessContext, ModelProfile
from rex.projects.context_store import ContextStore

__all__ = ["page_onboard"]

_PRESET_DOMAINS = [
    "Marketing", "Sales", "Finance", "Strategy", "Brand",
    "Research", "Product", "Engineering", "Legal", "HR",
    "Personal", "Operations",
]

_PROFILE_HELP = {
    ModelProfile.LOCAL: "Ollama only · free · slower · privacy-first",
    ModelProfile.BALANCED: "Gemini Flash + local · cheap · fast · recommended",
    ModelProfile.PREMIUM: "Claude / GPT-4 · best quality · highest cost",
    ModelProfile.CUSTOM: "Pick your own model per pipeline stage",
}


def _load_existing() -> BusinessContext:
    """Load existing project context or return defaults."""
    store = ContextStore()
    existing = store.get_for_project()
    return existing if existing else ContextStore.default()


def _render_questions(defaults: BusinessContext) -> BusinessContext:
    """Render the 3 wizard questions + profile picker. Returns the staged context."""
    st.subheader("1. What's this folder about?")
    business = st.text_input(
        "One sentence — Rex uses this to align categories.",
        value=defaults.business,
        placeholder="e.g., Accsell — AI-powered agentic sales platform",
    )

    st.subheader("2. Domains you care about")
    st.caption("Files outside these domains route to /_Unsorted/ for triage.")
    selected = st.multiselect(
        "Select your domains (multi-select)",
        _PRESET_DOMAINS,
        default=[d for d in defaults.domains if d in _PRESET_DOMAINS],
    )
    custom = st.text_input(
        "Add custom domains (comma-separated)",
        value=",".join(d for d in defaults.domains if d not in _PRESET_DOMAINS),
        placeholder="ResearchOps, ClientX, ...",
    )
    extra = [c.strip() for c in custom.split(",") if c.strip()]
    domains = selected + extra

    st.subheader("3. Confidence threshold")
    threshold = st.slider(
        "Files below this score route to /_Review/ for human triage.",
        min_value=0.5, max_value=0.95, value=float(defaults.confidence_threshold),
        step=0.05,
    )

    st.subheader("Model profile")
    profile = st.selectbox(
        "Which models should Rex use for this scan?",
        list(ModelProfile),
        format_func=lambda p: f"{p.value.title()} — {_PROFILE_HELP[p]}",
        index=list(ModelProfile).index(defaults.model_profile),
    )

    build_graph = st.checkbox(
        "Build knowledge graph (entities + relationships)",
        value=defaults.build_knowledge_graph,
        help="Runs entity extraction + GraphRAG concurrently with sort.",
    )

    return BusinessContext(
        business=business,
        domains=domains,
        confidence_threshold=threshold,
        model_profile=profile,
        build_knowledge_graph=build_graph,
    )


def _save_and_confirm(ctx: BusinessContext) -> None:
    """Persist context to project + per-job, show success."""
    store = ContextStore()
    project_path = store.save_for_project(ctx)
    st.success(f"✅ Saved project context → `{project_path}`")
    st.json(ctx.model_dump(mode="json"))
    st.session_state["business_context"] = ctx
    st.info("👉 Go to the **Scan** page to start a scan with this context.")


def page_onboard() -> None:
    """Onboarding wizard — captures BusinessContext for scans."""
    st.title("🚀 Onboard")
    st.write(
        "Tell Rex about your business once. It uses this to align categories, "
        "route low-confidence items to review, and pick the right models."
    )

    defaults = _load_existing()
    if defaults.business:
        st.caption(f"✏️  Editing existing context: _{defaults.business}_")

    ctx = _render_questions(defaults)

    st.markdown("---")
    col_save, col_clear = st.columns([1, 1])
    if col_save.button("💾 Save & Use", type="primary", use_container_width=True):
        if not ctx.business.strip():
            st.error("Please describe the folder in question 1.")
            return
        if not ctx.domains:
            st.error("Please pick at least one domain in question 2.")
            return
        _save_and_confirm(ctx)
    if col_clear.button("🗑️ Reset", use_container_width=True):
        st.session_state.pop("business_context", None)
        st.rerun()
