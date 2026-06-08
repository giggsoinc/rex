"""Editable Settings page — system config + secret management + classifier picker.

Sections:
  1. System (read-only) — deployment mode, vector store, paths
  2. Business context — quick-edit from Settings page (mirrors Onboarding)
  3. API keys — masked display + update; writes to .env.local
  4. Classifier choice — pick registered algorithm + parameters
"""

from __future__ import annotations

import streamlit as st

from rex.config import get_settings
from rex.ml.classifier import ClassifierRegistry
from rex.ml.classifier import algorithms as _algos  # noqa: F401 — triggers registration
from rex.models.business_context import BusinessContext, ModelProfile
from rex.projects.context_store import ContextStore
from rex.ui.secrets_io import is_set, list_known_keys, read_masked, write_secret

__all__ = ["page_settings"]


def _system_section() -> None:
    """Render the read-only system configuration block."""
    s = get_settings()
    st.subheader("🖥️ System (read-only)")
    st.json({
        "deployment_mode": s.deployment_mode.value,
        "llm_provider": s.llm_provider.value,
        "llm_model": s.llm_model,
        "embed_model": s.embed_model,
        "vector_store": s.vector_store.value,
        "vector_path": s.vector_path,
        "vision_provider": s.vision_provider.value,
        "storage_path": s.storage_path,
    })
    st.caption("Change via `.env.local` or `rex init`.")


def _business_context_section() -> None:
    """Render an editable BusinessContext block — mirrors Onboarding wizard."""
    st.subheader("🎯 Business Context")
    store = ContextStore()
    ctx = store.get_for_project() or ContextStore.default()

    biz = st.text_input("Business description", value=ctx.business)
    domains_str = st.text_input(
        "Domains (comma-separated)",
        value=", ".join(ctx.domains),
    )
    threshold = st.slider(
        "Confidence threshold",
        0.5, 0.95, float(ctx.confidence_threshold), step=0.05,
    )
    profile = st.selectbox(
        "Model profile",
        list(ModelProfile),
        format_func=lambda p: p.value.title(),
        index=list(ModelProfile).index(ctx.model_profile),
    )
    build_graph = st.checkbox(
        "Build knowledge graph in Phase 2",
        value=ctx.build_knowledge_graph,
    )

    if st.button("💾 Save business context", type="primary"):
        new_ctx = BusinessContext(
            business=biz,
            domains=[d.strip() for d in domains_str.split(",") if d.strip()],
            confidence_threshold=threshold,
            model_profile=profile,
            build_knowledge_graph=build_graph,
        )
        path = store.save_for_project(new_ctx)
        st.success(f"Saved → `{path}`")


def _secrets_section() -> None:
    """Render the masked secrets editor."""
    st.subheader("🔐 API Keys")
    st.caption(
        "Set / update keys. Values are masked once saved. "
        "Writes to `.env.local` in the project root."
    )
    for key in list_known_keys():
        col_label, col_input, col_status = st.columns([2, 3, 1])
        col_label.markdown(f"**{key}**")
        masked = read_masked(key)
        placeholder = masked or "not set"
        new_val = col_input.text_input(
            key, value="", placeholder=placeholder, label_visibility="collapsed",
            type="password", key=f"sec_{key}",
        )
        col_status.markdown("✅" if is_set(key) else "❌")
        if new_val:
            path = write_secret(key, new_val)
            st.success(f"`{key}` updated → `{path}`")


def _classifier_section() -> None:
    """Render the classifier selection block."""
    st.subheader("🧠 Classifier (per scan)")
    available = ClassifierRegistry.list_available()
    if not available:
        st.warning("No classifiers registered. Check `rex.ml.classifier.algorithms` imports.")
        return

    choice = st.selectbox("Algorithm", available, key="settings_clf_choice")
    if choice == "knn":
        k = st.slider("k (neighbors)", 1, 15, 5)
        st.caption(f"kNN with k={k}. Trained from `_decisions/*.user.json`.")
    elif choice == "llm_zero_shot":
        st.caption("LLM zero-shot — uses BusinessContext.domains as candidates.")
    elif choice == "ensemble":
        st.caption("Weighted vote across kNN + llm_zero_shot. Configure in code.")
    st.info(
        "Selection is per-scan: the Scan page will use this choice when it kicks "
        "off the next scan. Builder hooks pass these to ClassifierRouter."
    )


def page_settings() -> None:
    """Editable Settings page — system info + business context + secrets + classifier."""
    st.title("⚙️ Settings")
    tab_sys, tab_biz, tab_sec, tab_clf = st.tabs(
        ["🖥️ System", "🎯 Business", "🔐 Secrets", "🧠 Classifier"]
    )
    with tab_sys:
        _system_section()
    with tab_biz:
        _business_context_section()
    with tab_sec:
        _secrets_section()
    with tab_clf:
        _classifier_section()
