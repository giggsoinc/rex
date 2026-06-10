"""Routing tab for the Settings page — shows active profile + per-task model
+ recent cost from .raven/usage.jsonl.

Read-only display today; the active profile is set via BusinessContext
(Onboarding) or REX_LLM_PROFILE env var. Inline editing would require a
YAML editor — left for a future PR.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

from rex.ml.routing import get_router

__all__ = ["routing_section"]


def _load_recent_usage(hours: int = 24) -> tuple[int, float, dict, dict]:
    """Read .raven/usage.jsonl and return (calls, cost_usd, by_task, by_model).

    Only includes lines newer than `hours` ago. Best-effort: skips malformed
    lines silently.
    """
    log = Path(".raven/usage.jsonl")
    if not log.exists():
        return 0, 0.0, {}, {}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    calls = 0
    cost = 0.0
    by_task: dict[str, dict] = defaultdict(lambda: {"calls": 0, "cost": 0.0})
    by_model: dict[str, dict] = defaultdict(lambda: {"calls": 0, "cost": 0.0})
    try:
        for line in log.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
                if ts < cutoff:
                    continue
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
            calls += 1
            c = float(rec.get("cost_usd", 0.0))
            cost += c
            t = rec.get("task", "unknown")
            m = rec.get("model", "unknown")
            by_task[t]["calls"] += 1
            by_task[t]["cost"] += c
            by_model[m]["calls"] += 1
            by_model[m]["cost"] += c
    except OSError:
        pass
    return calls, cost, dict(by_task), dict(by_model)


def routing_section() -> None:
    """Render the routing config + usage block."""
    st.subheader("🚦 LLM Routing")
    st.caption(
        "Per-task model selection via LiteLLM. Set the active profile in "
        "🚀 Onboard → Model profile, or via REX_LLM_PROFILE env var. "
        "Edit `.raven/llm_routing.yaml` for full control."
    )
    try:
        router = get_router()
    except Exception as e:
        st.error(f"Failed to load routing config: {e}")
        return

    st.markdown(f"**Active profile:** `{router.config.active_profile}`")
    st.markdown("**Per-task chains:**")
    rows = []
    for task_name in sorted(router.config.tasks):
        t = router.config.tasks[task_name]
        rows.append({
            "task": task_name,
            "primary": t.primary,
            "fallback": ", ".join(t.fallback) or "—",
            "max $/call": (
                f"${t.max_cost_per_call_usd:.4f}"
                if t.max_cost_per_call_usd is not None else "—"
            ),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("**Last 24h usage** (from `.raven/usage.jsonl`)")
    calls, cost, by_task, by_model = _load_recent_usage(24)
    cols = st.columns(2)
    cols[0].metric("Calls", f"{calls:,}")
    cols[1].metric("Cost", f"${cost:.4f}")

    if by_task:
        with st.expander("By task"):
            st.dataframe(
                [{"task": k, "calls": v["calls"], "cost_usd": round(v["cost"], 4)}
                 for k, v in sorted(by_task.items())],
                use_container_width=True, hide_index=True,
            )
    if by_model:
        with st.expander("By model"):
            st.dataframe(
                [{"model": k, "calls": v["calls"], "cost_usd": round(v["cost"], 4)}
                 for k, v in sorted(by_model.items())],
                use_container_width=True, hide_index=True,
            )
