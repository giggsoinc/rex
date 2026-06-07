"""Drift detector — sha256 + path drift between a stored snapshot and disk reality.

Runs as a periodic job (cron / scheduler) and on-demand from Streamlit.

Three drift categories detected:
  1. CONTENT — file's sha256 has changed since indexing (file was edited)
  2. MISSING — file's path no longer exists (file was deleted/moved out)
  3. NEW     — file at path was not in prior snapshot (new file appeared)

The detector is pure observation — it does not fix drift. Actions (re-embed,
cleanup orphans, reclassify) are downstream responsibilities.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import structlog

logger = structlog.get_logger()

__all__ = ["DriftReport", "scan_drift"]


@dataclass
class DriftReport:
    """Summary of disk drift relative to a known snapshot."""

    content_drift: list[str] = field(default_factory=list)   # sha256 mismatched
    missing: list[str] = field(default_factory=list)         # path gone
    new: list[str] = field(default_factory=list)             # path appeared
    checked: int = 0

    @property
    def total_drift(self) -> int:
        """Count of all drift events across the three categories."""
        return len(self.content_drift) + len(self.missing) + len(self.new)

    @property
    def drift_ratio(self) -> float:
        """Fraction of checked files that drifted (0-1)."""
        return self.total_drift / max(self.checked, 1)

    def as_dict(self) -> dict:
        """Serialize for logging or report rendering."""
        return {
            "content_drift": self.content_drift,
            "missing": self.missing,
            "new": self.new,
            "checked": self.checked,
            "drift_ratio": round(self.drift_ratio, 4),
        }


def _sha256(path: Path, max_bytes: int = 64 * 1024 * 1024) -> str:
    """Compute sha256 of a file; cap at max_bytes for speed on huge files."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            data = f.read(max_bytes)
            h.update(data)
        return h.hexdigest()
    except OSError as e:
        logger.warning("drift_hash_failed", path=str(path), error=str(e)[:200])
        return ""


def scan_drift(
    prior_state: dict[str, str], source_root: str | Path,
) -> DriftReport:
    """Compare prior {path: sha256} snapshot against current disk state.

    Args:
        prior_state: dict mapping absolute path → sha256 hex from prior scan
        source_root: filesystem root to walk (current truth)

    Returns:
        DriftReport with content_drift / missing / new lists.
    """
    root = Path(source_root).expanduser().resolve()
    report = DriftReport()

    # Snapshot current paths + hashes
    current_paths: dict[str, str] = {}
    for p in root.rglob("*"):
        if p.is_file():
            current_paths[str(p)] = ""  # hash lazy below

    # Compare prior → current
    for path, prior_hash in prior_state.items():
        report.checked += 1
        p = Path(path)
        if not p.exists() or path not in current_paths:
            report.missing.append(path)
            continue
        current_hash = _sha256(p)
        current_paths[path] = current_hash
        if current_hash and current_hash != prior_hash:
            report.content_drift.append(path)

    # Anything in current but not prior → NEW
    for path in current_paths:
        if path not in prior_state:
            report.new.append(path)

    logger.info(
        "drift_scan_complete",
        checked=report.checked,
        drifted=report.total_drift,
        ratio=round(report.drift_ratio, 4),
    )
    return report
