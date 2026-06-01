"""Obsidian-compatible catalog markdown generators for the organizer.

Extracted from organizer.py to keep modules under the line limit. These are
pure functions operating on (catalog_dir, job, files, decisions).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from rex.agents.organizer_overview import write_overview_md
from rex.agents.organizer_sidecar import build_sidecar
from rex.models.schemas import FileRecord

# Re-exported so organizer.py can import the full catalog surface from here.
__all__ = [
    "build_sidecar",
    "write_index_md",
    "write_tags_md",
    "write_categories_md",
    "write_duplicates_md",
    "write_overview_md",
]


def write_index_md(catalog_dir: Path, job, files, decisions) -> None:
    """Write master index — every file, sortable."""
    lines = [
        f"# Index — {job.name if job else 'Rex Scan'}",
        "",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        f"Total files: {len(files)}",
        "",
        "| File | Category | Tags | Relevance | Action |",
        "|------|----------|------|-----------|--------|",
    ]
    for f in sorted(files, key=lambda x: x.filename.lower()):
        d = decisions.get(f.id)
        if not d:
            continue
        tags = ", ".join(d.tags) if d.tags else ""
        lines.append(
            f"| [[{f.filename}]] | {d.category} | {tags} | {d.relevance} | {d.action.value} |"
        )
    (catalog_dir / "index.md").write_text("\n".join(lines))


def write_tags_md(catalog_dir: Path, files, decisions) -> None:
    """Tag → files index."""
    tag_to_files: dict[str, list[str]] = defaultdict(list)
    for f in files:
        d = decisions.get(f.id)
        if not d:
            continue
        for tag in d.tags:
            tag_to_files[tag].append(f.filename)

    lines = ["# Tags", "", f"Generated: {datetime.utcnow().isoformat()}Z", ""]
    for tag in sorted(tag_to_files):
        lines.append(f"## #{tag}")
        lines.append("")
        for fn in sorted(set(tag_to_files[tag])):
            lines.append(f"- [[{fn}]]")
        lines.append("")
    (catalog_dir / "tags.md").write_text("\n".join(lines))


def write_categories_md(catalog_dir: Path, files, decisions) -> None:
    """Category tree — hierarchical."""
    cat_to_files: dict[str, list[FileRecord]] = defaultdict(list)
    for f in files:
        d = decisions.get(f.id)
        if not d:
            continue
        cat_to_files[d.category].append(f)

    lines = ["# Categories", "", f"Generated: {datetime.utcnow().isoformat()}Z", ""]
    for cat in sorted(cat_to_files):
        lines.append(f"## {cat}")
        lines.append("")
        lines.append(f"_{len(cat_to_files[cat])} files_")
        lines.append("")
        for f in sorted(cat_to_files[cat], key=lambda x: x.filename.lower()):
            d = decisions.get(f.id)
            action = d.action.value if d else "?"
            lines.append(f"- [[{f.filename}]] · {action}")
        lines.append("")
    (catalog_dir / "categories.md").write_text("\n".join(lines))


def write_duplicates_md(catalog_dir: Path, files, decisions) -> None:
    """Duplicate groups for review."""
    file_by_id = {f.id: f for f in files}
    dup_groups: dict[str, list[str]] = defaultdict(list)
    for f in files:
        d = decisions.get(f.id)
        if not d or not d.duplicate_of:
            continue
        original = file_by_id.get(d.duplicate_of)
        if original:
            dup_groups[original.filename].append(f"{f.filename} ({d.dedup_status.value})")

    lines = [
        "# Duplicates",
        "",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "",
    ]
    if not dup_groups:
        lines.append("_No duplicates detected._")
    else:
        for original, dups in sorted(dup_groups.items()):
            lines.append(f"## Original: [[{original}]]")
            lines.append("")
            for d in dups:
                lines.append(f"- {d}")
            lines.append("")
    (catalog_dir / "duplicates.md").write_text("\n".join(lines))
