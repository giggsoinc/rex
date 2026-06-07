"""INDEX.md generator for SortEngine — root catalog markdown.

Produces an Obsidian-friendly INDEX.md summarizing the sort run: domains
+ bucket counts, _Review and _Unsorted queues, status, confidence.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import structlog

from rex.agents.sort_engine_routing import SortDecision
from rex.agents.sort_engine_taxonomy import REVIEW_DIR
from rex.models.business_context import BusinessContext
from rex.models.schemas import FileDecision, FileRecord

logger = structlog.get_logger()

__all__ = ["write_index"]

Placement = tuple[FileRecord, FileDecision, SortDecision]


def _partition(placements: list[Placement]) -> tuple[
    dict[str, dict[str, list[Placement]]],
    list[Placement],
    list[Placement],
    list[float],
]:
    """Group placements into domain_buckets / review / unsorted; collect confidences."""
    domain_buckets: dict[str, dict[str, list[Placement]]] = defaultdict(
        lambda: defaultdict(list)
    )
    review_items: list[Placement] = []
    unsorted_items: list[Placement] = []
    confidences: list[float] = []
    for rec, dec, sort in placements:
        confidences.append(dec.confidence)
        if sort.needs_review:
            if REVIEW_DIR in str(sort.destination):
                review_items.append((rec, dec, sort))
            else:
                unsorted_items.append((rec, dec, sort))
        elif sort.domain is not None:
            domain_buckets[sort.domain][sort.bucket].append((rec, dec, sort))
    return domain_buckets, review_items, unsorted_items, confidences


def _render_domains(domain_buckets: dict[str, dict[str, list[Placement]]]) -> list[str]:
    """Render the ## Domains section."""
    lines: list[str] = ["## Domains", ""]
    for domain in sorted(domain_buckets):
        buckets = domain_buckets[domain]
        total_in_domain = sum(len(v) for v in buckets.values())
        lines.append(f"### {domain} ({total_in_domain} files)")
        lines.append("")
        for bucket in sorted(buckets):
            items = buckets[bucket]
            lines.append(
                f"- **{bucket}** ({len(items)}): see "
                f"[`{domain}/{bucket}/`](./{domain}/{bucket}/)"
            )
        lines.append("")
    return lines


def _render_queues(
    review_items: list[Placement], unsorted_items: list[Placement], domains: list[str]
) -> list[str]:
    """Render the _Review and _Unsorted queue sections."""
    lines: list[str] = []
    if review_items:
        lines += ["## ⚠️ _Review — Needs You (Low Confidence)", ""]
        for rec, dec, _ in review_items:
            lines.append(
                f"- [[{rec.filename}]] · guessed `{dec.category}` "
                f"(conf {dec.confidence:.2f}) — {dec.reasoning}"
            )
        lines.append("")
    if unsorted_items:
        lines += ["## 🔎 _Unsorted — No Domain Match", ""]
        for rec, dec, _ in unsorted_items:
            lines.append(
                f"- [[{rec.filename}]] · `{dec.category}` did not align "
                f"to your domains ({', '.join(domains)})"
            )
        lines.append("")
    return lines


def write_index(
    output_root: str | Path,
    context: BusinessContext,
    placements: list[Placement],
) -> Path:
    """Write the root INDEX.md for a sort run. Returns the index path."""
    out_root = Path(output_root).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    index_path = out_root / "INDEX.md"

    domain_buckets, review_items, unsorted_items, confidences = _partition(placements)
    avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0
    total = len(placements)

    header = [
        f"# Knowledge Index — {context.business or 'Rex Scan'}",
        "",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        f"Total files placed: **{total}** · Avg confidence: **{avg_conf:.2f}**",
        f"Status: **AWAITING REVIEW** — clear {len(review_items)} review + "
        f"{len(unsorted_items)} unsorted before serving.",
        "",
    ]
    footer = [
        "## Notes", "",
        "- Files are **copied**, not moved — source untouched.",
        "- Open this folder in Obsidian to navigate via wiki-links.",
        f"- Confidence threshold: {context.confidence_threshold}.",
        "",
    ]
    lines = (
        header
        + _render_domains(domain_buckets)
        + _render_queues(review_items, unsorted_items, context.domains)
        + footer
    )
    index_path.write_text("\n".join(lines))
    logger.info("sort_index_written", path=str(index_path), files=total)
    return index_path
