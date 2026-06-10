"""Routing config — load .raven/llm_routing.yaml into typed dataclasses.

Schema:
  tasks:
    <task_name>:
      primary: "<provider>/<model>"        # required
      fallback: ["<provider>/<model>", …]  # optional
      max_cost_per_call_usd: <float>       # optional guardrail
  profiles:
    <profile_name>: {task_overrides}       # optional bundles
  active_profile: <name>                   # selects which profile (else env)

Bundled defaults live in routing_defaults.yaml (shipped with the package).
User overrides go in .raven/llm_routing.yaml (per project) — values merge
on top of the bundled defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

__all__ = ["TaskRoute", "RoutingConfig", "load_routing_config"]

# Standard task names — pipeline stages refer to these by string.
KNOWN_TASKS = (
    "embed", "classify", "vision_describe", "entity_extraction", "reason",
)


@dataclass
class TaskRoute:
    """Per-task model selection."""

    primary: str                            # "provider/model" (LiteLLM format)
    fallback: list[str] = field(default_factory=list)
    max_cost_per_call_usd: float | None = None  # None = no budget guard

    def chain(self) -> list[str]:
        """Return [primary, *fallback] — the order to try models in."""
        return [self.primary, *self.fallback]


@dataclass
class RoutingConfig:
    """Top-level routing config — tasks + active profile."""

    tasks: dict[str, TaskRoute] = field(default_factory=dict)
    active_profile: str = "balanced"

    def get_task(self, name: str) -> TaskRoute:
        """Look up a task route; raise KeyError with helpful message."""
        if name not in self.tasks:
            raise KeyError(
                f"Task '{name}' has no route configured. Known tasks: "
                f"{sorted(self.tasks)}. Add to .raven/llm_routing.yaml or use "
                f"one of: {KNOWN_TASKS}."
            )
        return self.tasks[name]


def _route_from_dict(d: dict[str, Any]) -> TaskRoute:
    """Build a TaskRoute from a dict (YAML row)."""
    return TaskRoute(
        primary=str(d["primary"]),
        fallback=[str(x) for x in d.get("fallback", []) or []],
        max_cost_per_call_usd=(
            float(d["max_cost_per_call_usd"])
            if d.get("max_cost_per_call_usd") is not None else None
        ),
    )


def _bundled_defaults_path() -> Path:
    """Path to routing_defaults.yaml shipped inside the package."""
    return Path(__file__).parent / "routing_defaults.yaml"


def load_routing_config(
    user_path: Path | str | None = None,
    profile: str | None = None,
) -> RoutingConfig:
    """Load routing config — bundled defaults + optional user overrides.

    Args:
        user_path: Path to user's .raven/llm_routing.yaml (or None to skip).
        profile: Active profile name (overrides what's in YAML).

    Returns:
        RoutingConfig with the merged tasks + active profile.
    """
    import yaml

    # Load bundled defaults (always present)
    raw: dict[str, Any] = {}
    bundled = _bundled_defaults_path()
    if bundled.exists():
        raw = yaml.safe_load(bundled.read_text()) or {}

    # Layer user overrides on top, if present
    if user_path is not None:
        up = Path(user_path).expanduser()
        if up.exists():
            user_raw = yaml.safe_load(up.read_text()) or {}
            # Shallow merge — user wins per top-level key
            for k, v in user_raw.items():
                if k == "tasks" and isinstance(v, dict):
                    raw.setdefault("tasks", {}).update(v)
                else:
                    raw[k] = v
            logger.info("routing_user_overrides_loaded", path=str(up))

    # Resolve task → TaskRoute
    tasks = {
        name: _route_from_dict(spec)
        for name, spec in (raw.get("tasks") or {}).items()
    }

    # Apply profile overrides (profile selects a sub-dict of task_overrides)
    chosen_profile = profile or raw.get("active_profile", "balanced")
    profiles = raw.get("profiles") or {}
    overrides = (profiles.get(chosen_profile) or {}).get("task_overrides") or {}
    for task_name, override in overrides.items():
        if task_name in tasks:
            base = tasks[task_name]
            tasks[task_name] = TaskRoute(
                primary=override.get("primary", base.primary),
                fallback=override.get("fallback", base.fallback),
                max_cost_per_call_usd=override.get(
                    "max_cost_per_call_usd", base.max_cost_per_call_usd
                ),
            )

    return RoutingConfig(tasks=tasks, active_profile=chosen_profile)
