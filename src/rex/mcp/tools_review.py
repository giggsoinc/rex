"""MCP review/HITL tools — expose Rex's review queue to Claude / MCP clients.

Six tools delivered (per the locked architecture):

  rex_pending_review(output_path)         — list items needing HITL triage
  rex_review_card(output_path, index)     — get one item's details
  rex_decide(output_path, name, category) — apply a domain decision
  rex_decide_bulk(output_path, items, c)  — batch apply same category
  rex_list_categories(output_path)        — list current taxonomy
  rex_business_context(output_path)       — get current BusinessContext

All MCP tools must be JSON-serializable in / out. Errors raise as
exceptions so the MCP client gets a structured failure response.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from rex.projects.context_store import ContextStore
from rex.ui.review_queue import apply_decision, scan_pending

logger = structlog.get_logger()

__all__ = ["register_review_tools"]


def _items_summary(output_path: str) -> list[dict[str, Any]]:
    """Return a JSON-serializable list of pending items at output_path."""
    items = scan_pending(output_path)
    return [
        {
            "index": i,
            "filename": item.filename,
            "path": str(item.path),
            "reason": item.reason,
            "bucket_hint": item.bucket_hint,
            "size_bytes": item.path.stat().st_size if item.path.exists() else 0,
        }
        for i, item in enumerate(items)
    ]


def register_review_tools(app: Any) -> None:
    """Attach review / HITL tools to a FastMCP app instance."""

    @app.tool()
    async def rex_pending_review(output_path: str) -> dict[str, Any]:
        """List items awaiting HITL triage in a Rex scan output folder.

        Returns: {total: int, review: int, unsorted: int, items: [...] }
        """
        items = _items_summary(output_path)
        review = sum(1 for i in items if i["reason"] == "_Review")
        unsorted = sum(1 for i in items if i["reason"] == "_Unsorted")
        return {"total": len(items), "review": review, "unsorted": unsorted, "items": items}

    @app.tool()
    async def rex_review_card(output_path: str, index: int) -> dict[str, Any]:
        """Get full details of a single pending item by index."""
        items = _items_summary(output_path)
        if not (0 <= index < len(items)):
            raise IndexError(f"index {index} out of range; have {len(items)} items")
        return items[index]

    @app.tool()
    async def rex_decide(
        output_path: str, filename: str, category: str, note: str = "",
    ) -> dict[str, Any]:
        """Move a pending file to {category}/{bucket}/. Persists for learning loop.

        Returns: {moved_to: str, decision: str, filename: str}
        """
        # Find the matching PendingItem
        from rex.ui.review_queue import scan_pending
        for item in scan_pending(output_path):
            if item.filename == filename:
                new_path = apply_decision(item, output_path, category, note=note)
                return {
                    "moved_to": str(new_path) if new_path else None,
                    "decision": category,
                    "filename": filename,
                }
        raise FileNotFoundError(f"No pending item with filename '{filename}'")

    @app.tool()
    async def rex_decide_bulk(
        output_path: str, filenames: list[str], category: str, note: str = "",
    ) -> dict[str, Any]:
        """Apply the same category to many files in one shot."""
        results: list[dict[str, Any]] = []
        from rex.ui.review_queue import scan_pending
        items = {it.filename: it for it in scan_pending(output_path)}
        for fn in filenames:
            if fn not in items:
                results.append({"filename": fn, "ok": False, "error": "not pending"})
                continue
            new_path = apply_decision(items[fn], output_path, category, note=note)
            results.append({
                "filename": fn, "ok": True,
                "moved_to": str(new_path) if new_path else None,
            })
        return {"category": category, "count": len(filenames), "results": results}

    @app.tool()
    async def rex_list_categories(output_path: str) -> dict[str, Any]:
        """List discovered category folders at the output root."""
        root = Path(output_path).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(f"Output folder not found: {root}")
        cats = sorted(
            p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")
        )
        sub = {
            cat: sorted(c.name for c in (root / cat).iterdir() if c.is_dir())
            for cat in cats
        }
        return {"categories": cats, "subcategories": sub}

    @app.tool()
    async def rex_business_context(output_path: str = "") -> dict[str, Any]:
        """Return the current BusinessContext (project or default)."""
        store = ContextStore()
        ctx = store.get_for_project() or ContextStore.default()
        return ctx.model_dump(mode="json")

    logger.info("mcp_review_tools_registered", count=6)
