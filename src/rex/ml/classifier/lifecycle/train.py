"""Training helpers — bootstrap labeled examples from HITL decision history.

Reads {output_root}/_decisions/*.user.json (written by review_queue.apply_decision)
and {job_id}/decisions/{file_id}.json (router output) and produces a
list of (embedding, label) tuples ready for any Classifier.fit() call.

Decisions store the chosen domain. The embedding comes from a vector store
lookup keyed on file path or sha256. We accept a callable resolver so the
trainer doesn't depend on a concrete vector backend.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import structlog

logger = structlog.get_logger()

__all__ = ["bootstrap_from_decisions"]

EmbeddingResolver = Callable[[str], list[float] | None]


def _load_user_decisions(output_root: Path) -> list[dict]:
    """Read _decisions/*.user.json — produced by the HITL Review page."""
    out = []
    decisions_dir = output_root / "_decisions"
    if not decisions_dir.exists():
        return out
    for f in decisions_dir.glob("*.user.json"):
        try:
            out.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("decision_load_failed", path=str(f), error=str(e)[:200])
    return out


def _load_router_decisions(job_dir: Path) -> list[dict]:
    """Read router-produced decisions for a job."""
    out = []
    decisions_dir = job_dir / "decisions"
    if not decisions_dir.exists():
        return out
    for f in decisions_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            data["_source"] = "router"
            out.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("router_decision_load_failed", path=str(f), error=str(e)[:200])
    return out


def bootstrap_from_decisions(
    output_root: str | Path,
    embedding_resolver: EmbeddingResolver,
    job_dirs: list[Path] | None = None,
    include_router_decisions: bool = False,
) -> list[tuple[list[float], str]]:
    """Build a (embedding, label) list from HITL + optional router decisions.

    Args:
        output_root: root of a Rex scan output (contains _decisions/)
        embedding_resolver: callable that, given a filename or sha256, returns
                            the file's embedding (or None if not stored)
        job_dirs: optional list of job directories to additionally pull router
                  decisions from. Useful for first-scan bootstrapping.
        include_router_decisions: if True, also use router-produced labels
                                  as weak supervision. Default False (HITL only).

    Returns:
        list of (embedding, label) tuples for Classifier.fit().
    """
    out_root = Path(output_root).expanduser().resolve()
    labeled: list[tuple[list[float], str]] = []

    # HITL labels (strong supervision)
    for d in _load_user_decisions(out_root):
        key = d.get("filename") or d.get("file_id")
        label = d.get("decision") or d.get("user_label")
        if not key or not label or label in {"TRASHED", "_Review", "_Unsorted"}:
            continue
        emb = embedding_resolver(key)
        if emb is None:
            continue
        labeled.append((emb, label))

    # Router labels (weak supervision, optional)
    if include_router_decisions:
        for job in job_dirs or []:
            for d in _load_router_decisions(job):
                key = d.get("file_id") or d.get("filename")
                label = d.get("category")
                if not key or not label:
                    continue
                emb = embedding_resolver(key)
                if emb is None:
                    continue
                # Keep only first segment of nested categories ("Marketing/Q3" → "Marketing")
                label = str(label).split("/")[0].strip()
                if label:
                    labeled.append((emb, label))

    logger.info("bootstrap_complete", total=len(labeled))
    return labeled
