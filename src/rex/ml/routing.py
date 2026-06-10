"""LiteLLM task router — entry point for all model calls in Rex.

Use:
    from rex.ml.routing import get_router
    router = get_router()                    # cached singleton
    text = await router.chat(task="classify", prompt="…", system="…")
    vec  = await router.embed(task="embed", text="…")

The router:
  1. Looks up the task's primary + fallback chain (routing_config).
  2. Calls LiteLLM via the unified completion / embedding API.
  3. On failure (or budget exceeded), falls back to the next model.
  4. Logs every call to .raven/usage.jsonl via usage_log.

Zero behavior change for callers that DON'T use routing yet — existing
ModelProvider stays untouched until PR 2 migrates the hot path.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import structlog

from rex.ml.routing_config import RoutingConfig, TaskRoute, load_routing_config
from rex.ml.usage_log import log_call

logger = structlog.get_logger()

__all__ = ["LLMRouter", "get_router", "reset_router"]


def _default_user_path() -> Path:
    """Where users override defaults — .raven/llm_routing.yaml in CWD."""
    return Path(".raven") / "llm_routing.yaml"


class LLMRouter:
    """Task-aware LLM router using LiteLLM under the hood."""

    def __init__(self, config: RoutingConfig | None = None) -> None:
        """Construct with an optional pre-loaded config; else load defaults."""
        self.config = config or load_routing_config(_default_user_path())

    def _is_over_budget(self, route: TaskRoute, cost: float) -> bool:
        """True if the call's cost exceeds the route's max_cost_per_call_usd."""
        cap = route.max_cost_per_call_usd
        return cap is not None and cost > cap

    async def chat(
        self, *, task: str, prompt: str, system: str = "",
        json_mode: bool = False, **kwargs: Any,
    ) -> str:
        """Run a chat completion for the task, following the fallback chain."""
        from litellm import acompletion, completion_cost

        route = self.config.get_task(task)
        messages = (
            [{"role": "system", "content": system}] if system else []
        ) + [{"role": "user", "content": prompt}]
        response_format = {"type": "json_object"} if json_mode else None

        last_err: Exception | None = None
        for idx, model in enumerate(route.chain()):
            start = time.monotonic()
            try:
                resp = await acompletion(
                    model=model, messages=messages,
                    response_format=response_format, **kwargs,
                )
                duration = int((time.monotonic() - start) * 1000)
                usage = getattr(resp, "usage", None) or {}
                try:
                    cost = float(completion_cost(completion_response=resp) or 0.0)
                except Exception:
                    cost = 0.0
                if idx > 0 and self._is_over_budget(route, cost):
                    last_err = ValueError(f"budget exceeded: {cost} > {route.max_cost_per_call_usd}")
                    continue
                log_call(
                    task=task, model=model,
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                    cost_usd=cost, fallback_used=(idx > 0), duration_ms=duration,
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                last_err = e
                logger.warning("router_chat_failed", task=task, model=model, idx=idx, error=str(e)[:160])
                continue
        # All models failed
        log_call(task=task, model=route.primary, fallback_used=True,
                 extra={"error": str(last_err)[:160] if last_err else "unknown"})
        raise RuntimeError(f"All models failed for task={task}: {last_err}")

    async def embed(self, *, task: str, text: str) -> list[float]:
        """Embed text via the task's primary model, with fallback."""
        from litellm import aembedding

        route = self.config.get_task(task)
        last_err: Exception | None = None
        for idx, model in enumerate(route.chain()):
            start = time.monotonic()
            try:
                resp = await aembedding(model=model, input=text)
                duration = int((time.monotonic() - start) * 1000)
                vec = resp["data"][0]["embedding"]
                log_call(
                    task=task, model=model, input_tokens=len(text.split()),
                    output_tokens=0, cost_usd=0.0,
                    fallback_used=(idx > 0), duration_ms=duration,
                )
                return list(vec)
            except Exception as e:
                last_err = e
                logger.warning("router_embed_failed", task=task, model=model, idx=idx, error=str(e)[:160])
                continue
        raise RuntimeError(f"All embedders failed for task={task}: {last_err}")


# --- Cached singleton accessors ---

_ROUTER: LLMRouter | None = None


def get_router(force_reload: bool = False) -> LLMRouter:
    """Return a cached LLMRouter instance. Set force_reload=True to rebuild."""
    global _ROUTER
    if _ROUTER is None or force_reload:
        profile_env = os.environ.get("REX_LLM_PROFILE", "").strip() or None
        _ROUTER = LLMRouter(load_routing_config(_default_user_path(), profile=profile_env))
    return _ROUTER


def reset_router() -> None:
    """Clear the cached router — used by tests."""
    global _ROUTER
    _ROUTER = None
