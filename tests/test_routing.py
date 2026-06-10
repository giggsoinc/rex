"""Tests for the LiteLLM task router (PR 1 foundation)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rex.ml.routing import LLMRouter, get_router, reset_router
from rex.ml.routing_config import RoutingConfig, TaskRoute, load_routing_config
from rex.ml.usage_log import log_call


def test_bundled_defaults_loadable():
    """Bundled YAML + 5 standard tasks present."""
    cfg = load_routing_config(None)
    for task in ("embed", "classify", "vision_describe", "entity_extraction", "reason"):
        assert task in cfg.tasks, f"task '{task}' missing from defaults"
    assert cfg.active_profile == "balanced"


def test_default_chain_has_local_first():
    """The balanced profile uses Ollama as primary for embed + classify."""
    cfg = load_routing_config(None)
    assert cfg.get_task("embed").primary.startswith("ollama/")
    assert cfg.get_task("classify").primary.startswith("ollama/")


def test_classify_has_cloud_fallback():
    """Classify has a Gemini fallback for when local Ollama fails."""
    cfg = load_routing_config(None)
    fb = cfg.get_task("classify").fallback
    assert any("gemini" in m for m in fb), f"classify should have gemini fallback, got {fb}"


def test_profile_overrides_apply(tmp_path: Path):
    """'local' profile should rewrite vision_describe to ollama."""
    cfg = load_routing_config(None, profile="local")
    assert cfg.active_profile == "local"
    assert cfg.get_task("vision_describe").primary.startswith("ollama/")


def test_user_overrides_merge(tmp_path: Path):
    """User YAML overrides win over bundled defaults."""
    user = tmp_path / "llm_routing.yaml"
    user.write_text(
        "tasks:\n"
        "  classify:\n"
        "    primary: openai/gpt-4o-mini\n"
        "    fallback: []\n"
    )
    cfg = load_routing_config(user)
    assert cfg.get_task("classify").primary == "openai/gpt-4o-mini"
    # Other tasks should still come from defaults
    assert cfg.get_task("embed").primary.startswith("ollama/")


def test_task_route_chain_returns_primary_then_fallbacks():
    """TaskRoute.chain() yields primary first, then fallbacks in order."""
    r = TaskRoute(primary="a/x", fallback=["b/y", "c/z"])
    assert r.chain() == ["a/x", "b/y", "c/z"]


def test_get_task_raises_for_unknown():
    """Unknown task name raises KeyError with helpful message."""
    cfg = RoutingConfig(tasks={"classify": TaskRoute(primary="ollama/q")})
    with pytest.raises(KeyError, match="Task 'nope' has no route"):
        cfg.get_task("nope")


def test_usage_log_writes_jsonl(tmp_path: Path):
    """log_call appends a parseable JSON line per call."""
    path = tmp_path / "usage.jsonl"
    log_call(
        task="embed", model="ollama/test", input_tokens=10,
        output_tokens=0, cost_usd=0.0, fallback_used=False,
        duration_ms=42, path=path,
    )
    log_call(
        task="classify", model="gemini/flash", input_tokens=200,
        output_tokens=50, cost_usd=0.00015, fallback_used=True,
        duration_ms=380, path=path,
    )
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["task"] == "embed" and first["model"] == "ollama/test"
    assert second["fallback_used"] is True
    assert second["cost_usd"] == 0.00015


def test_router_singleton_caches(tmp_path: Path, monkeypatch):
    """get_router() returns a cached instance until reset_router()."""
    reset_router()
    r1 = get_router()
    r2 = get_router()
    assert r1 is r2
    reset_router()
    r3 = get_router()
    assert r3 is not r1


def test_router_construction_with_explicit_config():
    """LLMRouter(config=…) bypasses YAML load — handy for tests."""
    cfg = RoutingConfig(tasks={"embed": TaskRoute(primary="ollama/test")})
    router = LLMRouter(config=cfg)
    assert router.config.get_task("embed").primary == "ollama/test"
