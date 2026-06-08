"""Pure routing decision logic for SortEngine.

resolve_destination() is a pure function: takes (FileRecord, FileDecision,
BusinessContext, output_root) → SortDecision. No side effects, easy to test.
"""

from __future__ import annotations

from pathlib import Path

from rex.agents.sort_engine_taxonomy import (
    ARCHIVE_DIR,
    REVIEW_DIR,
    TRASH_DIR,
    UNSORTED_DIR,
    extension_to_bucket,
    safe_segment,
)
from rex.models.business_context import BusinessContext
from rex.models.schemas import FileAction, FileDecision, FileRecord

__all__ = ["SortDecision", "resolve_destination", "align_to_domain"]


class SortDecision:
    """Pure decision record — where this file should go and why."""

    __slots__ = ("destination", "bucket", "domain", "reason", "needs_review")

    def __init__(
        self,
        destination: Path,
        bucket: str,
        domain: str | None,
        reason: str,
        needs_review: bool,
    ) -> None:
        """Construct a sort decision (pure value object)."""
        self.destination = destination
        self.bucket = bucket
        self.domain = domain
        self.reason = reason
        self.needs_review = needs_review

    def as_dict(self) -> dict:
        """Serialize for logging / decision history."""
        return {
            "destination": str(self.destination),
            "bucket": self.bucket,
            "domain": self.domain,
            "reason": self.reason,
            "needs_review": self.needs_review,
        }


def align_to_domain(category: str, domains: list[str]) -> str | None:
    """Snap router's category to the closest declared domain.

    Match strategy: case-insensitive substring match against domain list.
    Returns the matched domain or None if no domain fits.
    """
    if not domains:
        # No constraints — accept router's first segment verbatim
        return category.split("/")[0].strip() or None
    cat_lower = category.lower()
    for d in domains:
        if d.lower() in cat_lower or cat_lower in d.lower():
            return d
    return None


def resolve_destination(
    file_record: FileRecord,
    decision: FileDecision,
    context: BusinessContext,
    output_root: Path,
) -> SortDecision:
    """Decide where the file goes — pure function, no side effects.

    Routing priorities:
      1. TRASH action → _Trash/{bucket}/
      2. Confidence < threshold → _Review/
      3. Category doesn't match any domain → _Unsorted/{bucket}/
      4. ARCHIVE action → _Archive/{domain}/{bucket}/
      5. Normal KEEP → {domain}/{bucket}/
    """
    bucket = extension_to_bucket(file_record.extension)

    if decision.action == FileAction.TRASH:
        dest = output_root / TRASH_DIR / bucket / file_record.filename
        return SortDecision(dest, bucket, None, "marked TRASH by router", False)

    if decision.confidence < context.confidence_threshold:
        dest = output_root / REVIEW_DIR / file_record.filename
        return SortDecision(
            dest, bucket, None,
            f"confidence {decision.confidence:.2f} < threshold {context.confidence_threshold}",
            True,
        )

    domain = align_to_domain(decision.category, context.domains)
    if domain is None:
        dest = output_root / UNSORTED_DIR / bucket / file_record.filename
        return SortDecision(
            dest, bucket, None,
            f"category '{decision.category}' did not match any declared domain",
            True,
        )

    safe_domain = safe_segment(domain)
    if decision.action == FileAction.ARCHIVE:
        dest = output_root / ARCHIVE_DIR / safe_domain / bucket / file_record.filename
    else:
        dest = output_root / safe_domain / bucket / file_record.filename
    return SortDecision(dest, bucket, domain, "normal classification", False)
