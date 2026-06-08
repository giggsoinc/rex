"""Review queue helpers — scan job output for items needing HITL triage.

A "pending item" is a file currently in /_Review/ or /_Unsorted/ inside a
job's output folder. The Review page consumes these items and lets the user
re-classify them.

Decisions persist to {job_dir}/decisions/{file_id}.user.json so the next scan
can use them as learning signal.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from rex.agents.sort_engine_taxonomy import (
    REVIEW_DIR,
    UNSORTED_DIR,
    extension_to_bucket,
    safe_segment,
)

__all__ = ["PendingItem", "scan_pending", "apply_decision"]


@dataclass
class PendingItem:
    """One item awaiting HITL triage in the output folder."""

    path: Path
    filename: str
    bucket_hint: str
    reason: str  # "_Review" or "_Unsorted"


def scan_pending(output_root: str | Path) -> list[PendingItem]:
    """Walk output folder and collect items in _Review/ and _Unsorted/."""
    root = Path(output_root).expanduser().resolve()
    items: list[PendingItem] = []
    for special, reason in [(REVIEW_DIR, "_Review"), (UNSORTED_DIR, "_Unsorted")]:
        special_dir = root / special
        if not special_dir.exists():
            continue
        for p in sorted(special_dir.rglob("*")):
            if p.is_file():
                items.append(
                    PendingItem(
                        path=p,
                        filename=p.name,
                        bucket_hint=extension_to_bucket(p.suffix),
                        reason=reason,
                    )
                )
    return items


def apply_decision(
    item: PendingItem,
    output_root: str | Path,
    chosen_domain: str | None,
    action: str = "keep",
    note: str = "",
) -> Path | None:
    """Move an item from review to its chosen domain/bucket — or trash.

    Returns the new destination path, or None if trashed (file deleted from
    output folder; source folder is never modified).
    """
    root = Path(output_root).expanduser().resolve()

    if action == "trash":
        try:
            item.path.unlink()
        except OSError:
            pass
        _log_decision(item, root, "TRASHED", note)
        return None

    if not chosen_domain:
        return None

    safe_domain = safe_segment(chosen_domain)
    bucket = item.bucket_hint
    new_path = root / safe_domain / bucket / item.filename
    new_path.parent.mkdir(parents=True, exist_ok=True)

    if new_path.exists() and new_path != item.path:
        stem, suffix = new_path.stem, new_path.suffix
        new_path = new_path.parent / f"{stem}__reviewed{suffix}"

    shutil.move(str(item.path), str(new_path))
    _log_decision(item, root, chosen_domain, note)
    return new_path


def _log_decision(item: PendingItem, root: Path, outcome: str, note: str) -> None:
    """Persist a user decision JSON record for learning loop."""
    log_dir = root / "_decisions"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{item.path.stem}.user.json"
    payload = {
        "filename": item.filename,
        "previous_location": item.reason,
        "decision": outcome,
        "note": note,
    }
    log_path.write_text(json.dumps(payload, indent=2))
