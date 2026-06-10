"""Usage log — append one JSON line per LLM call to .raven/usage.jsonl.

Schema (per line):
  ts:               iso8601 timestamp
  task:             standard task name (embed / classify / vision_describe / …)
  model:            "provider/model" actually used (after fallback)
  input_tokens:     int (best effort)
  output_tokens:    int (best effort)
  cost_usd:         float (best effort — LiteLLM-derived)
  fallback_used:    bool — true if primary failed and fallback served
  duration_ms:      int — wall time for the call

Read by:
  - rex CLI:                       `rex usage --since 24h`
  - Raven dashboard:               ~/RavenVault/dashboard.html (when wired)
  - Streamlit Settings → Routing:  shows last 24h spend per task per model

The log is append-only, line-delimited JSON — easy to tail / grep / pipe.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

__all__ = ["log_call", "default_log_path"]


def default_log_path() -> Path:
    """Default location for the usage log — .raven/usage.jsonl in the CWD."""
    return Path(".raven") / "usage.jsonl"


def log_call(
    *,
    task: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    fallback_used: bool = False,
    duration_ms: int = 0,
    path: Path | str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one usage record to the log. Best-effort — never raises.

    Args:
        task: standard task name (one of routing.KNOWN_TASKS).
        model: provider/model string actually served the call.
        input_tokens / output_tokens: token counts from the provider response.
        cost_usd: cost estimate from LiteLLM.completion_cost (0.0 if unknown).
        fallback_used: True if primary failed and a fallback served.
        duration_ms: wall time for the call.
        path: override log path (default: default_log_path()).
        extra: any additional fields to merge in (e.g. error message).
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "task": task,
        "model": model,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "cost_usd": round(float(cost_usd), 6),
        "fallback_used": bool(fallback_used),
        "duration_ms": int(duration_ms),
    }
    if extra:
        record.update(extra)

    target = Path(path).expanduser() if path else default_log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError as e:
        logger.warning("usage_log_write_failed", path=str(target), error=str(e)[:160])
