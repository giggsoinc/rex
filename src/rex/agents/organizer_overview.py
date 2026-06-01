"""Overview catalog page generator for the organizer.

Extracted from organizer_catalog.py to keep modules under the line limit.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path


def write_overview_md(catalog_dir: Path, job, files, decisions) -> None:
    """High-level summary — links into the other docs."""
    cats = {decisions[fid].category for fid in decisions}
    action_counts: dict[str, int] = defaultdict(int)
    relevance_counts: dict[int, int] = defaultdict(int)
    for d in decisions.values():
        action_counts[d.action.value] += 1
        relevance_counts[d.relevance] += 1
    dup_count = sum(1 for d in decisions.values() if d.duplicate_of)

    lines = [
        f"# {job.name if job else 'Rex Scan'} — Overview",
        "",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "",
        "## Stats",
        "",
        f"- Files scanned: **{len(files)}**",
        f"- Classified: **{len(decisions)}**",
        f"- Duplicates: **{dup_count}**",
        f"- Categories: **{len(cats)}**",
        "",
        "## Actions",
        "",
    ]
    for action in ("keep", "archive", "trash"):
        lines.append(f"- {action}: **{action_counts.get(action, 0)}**")
    lines.extend([
        "",
        "## Relevance",
        "",
    ])
    for r in (5, 4, 3, 2, 1):
        lines.append(f"- {r}: **{relevance_counts.get(r, 0)}**")
    lines.extend([
        "",
        "## Browse",
        "",
        "- [[index|Index — every file]]",
        "- [[categories|Category tree]]",
        "- [[tags|Tag cloud]]",
        "- [[duplicates|Duplicates for review]]",
        "",
    ])
    (catalog_dir / "overview.md").write_text("\n".join(lines))
