"""Organizer agent — places files into organized output, writes catalog.

Copy semantics by default (never modifies source). Writes per-file metadata
sidecars and Obsidian-compatible catalog markdown.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import structlog

from rex.config import Settings, get_settings
from rex.models.schemas import FileAction, FileDecision, FileRecord
from rex.orchestrator.state import JobStore
from rex.plugins.local_fs import LocalFSPlugin

logger = structlog.get_logger()


# Folders within the organized output
TRASH_DIR = "_Trash"
FLAGGED_DIR = "_Flagged"
ARCHIVE_DIR = "_Archive"
CATALOG_DIR = "_catalog"
METADATA_DIR = "_metadata"


SAFE_PATH_RE = re.compile(r"[^a-zA-Z0-9._\-/]")


def safe_path_segment(s: str) -> str:
    """Sanitize a path segment — no spaces, no special chars."""
    s = s.strip().strip("/")
    s = s.replace("\\", "/")
    # Keep slashes for nested categories
    s = SAFE_PATH_RE.sub("_", s)
    return s or "Unsorted"


class LocalOrganizer:
    """Organizer for the local filesystem backend.

    Idempotent: re-organizing same job overwrites sidecars but skips file copy
    if destination already exists with the same hash.
    """

    def __init__(
        self,
        job_store: JobStore,
        settings: Settings | None = None,
    ) -> None:
        self.jobs = job_store
        self.settings = settings or get_settings()
        self.fs = LocalFSPlugin()

    async def organize(
        self,
        file_record: FileRecord,
        decision: FileDecision,
        output_root: str,
    ) -> str:
        """Place one file. Returns the new path, or '' if skipped."""
        out_root = Path(output_root).expanduser().resolve()
        out_root.mkdir(parents=True, exist_ok=True)

        # Pick destination folder based on action + category
        if decision.action == FileAction.TRASH:
            dest_dir = out_root / TRASH_DIR / safe_path_segment(decision.category)
        elif decision.action == FileAction.ARCHIVE:
            dest_dir = out_root / ARCHIVE_DIR / safe_path_segment(decision.category)
        else:
            dest_dir = out_root / safe_path_segment(decision.category)

        # Flag if relevance is low but action is keep
        if decision.relevance <= 2 and decision.action == FileAction.KEEP:
            dest_dir = out_root / FLAGGED_DIR / safe_path_segment(decision.category)

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / file_record.filename

        # Conflict resolution: if same name exists but different hash, suffix it
        if dest_path.exists():
            try:
                existing_size = dest_path.stat().st_size
                if existing_size != file_record.size_bytes:
                    # Different file with same name — add hash suffix
                    stem = dest_path.stem
                    suffix = dest_path.suffix
                    short_hash = file_record.sha256_hash[:8]
                    dest_path = dest_dir / f"{stem}__{short_hash}{suffix}"
            except Exception:
                pass

        # Copy file (skip if already in place)
        if not dest_path.exists():
            try:
                await self.fs.copy(file_record.original_path, str(dest_path))
            except Exception as e:
                logger.error("organizer_copy_failed", src=file_record.original_path, dst=str(dest_path), error=str(e))
                return ""

        # Write metadata sidecar
        sidecar_dir = out_root / METADATA_DIR
        sidecar_dir.mkdir(parents=True, exist_ok=True)
        sidecar_path = sidecar_dir / f"{file_record.sha256_hash[:16]}.json"
        sidecar = {
            "file_id": file_record.id,
            "job_id": file_record.job_id,
            "original_path": file_record.original_path,
            "new_path": str(dest_path),
            "filename": file_record.filename,
            "sha256": file_record.sha256_hash,
            "size_bytes": file_record.size_bytes,
            "mime_type": file_record.mime_type,
            "media_type": file_record.media_type.value,
            "modified_at": file_record.modified_at.isoformat() if file_record.modified_at else None,
            "category": decision.category,
            "tags": decision.tags,
            "relevance": decision.relevance,
            "action": decision.action.value,
            "dedup_status": decision.dedup_status.value,
            "duplicate_of": decision.duplicate_of,
            "reasoning": decision.reasoning,
            "extracted_text_preview": (file_record.extracted_text or "")[:500],
            "image_description": file_record.image_description,
            "entity_type": decision.entity_type,
            "relation_hints": decision.relation_hints,
            "organized_at": datetime.utcnow().isoformat() + "Z",
        }
        sidecar_path.write_text(json.dumps(sidecar, indent=2))

        return str(dest_path)

    async def finalize(self, job_id: str, output_root: str) -> None:
        """Build Obsidian-compatible catalog markdown after all files placed."""
        out_root = Path(output_root).expanduser().resolve()
        catalog_dir = out_root / CATALOG_DIR
        catalog_dir.mkdir(parents=True, exist_ok=True)

        # Load all files + decisions
        files = await self.jobs.list_files(job_id)
        decisions = await self.jobs.list_decisions(job_id)
        job = await self.jobs.get_job(job_id)

        if not files:
            logger.warning("finalize_no_files", job_id=job_id)
            return

        await self._write_index_md(catalog_dir, job, files, decisions)
        await self._write_tags_md(catalog_dir, files, decisions)
        await self._write_categories_md(catalog_dir, files, decisions)
        await self._write_duplicates_md(catalog_dir, files, decisions)
        await self._write_overview_md(catalog_dir, job, files, decisions)
        logger.info("catalog_written", job_id=job_id, files=len(files), dir=str(catalog_dir))

    # --- Catalog generators ---

    async def _write_index_md(self, catalog_dir: Path, job, files, decisions) -> None:
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

    async def _write_tags_md(self, catalog_dir: Path, files, decisions) -> None:
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

    async def _write_categories_md(self, catalog_dir: Path, files, decisions) -> None:
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

    async def _write_duplicates_md(self, catalog_dir: Path, files, decisions) -> None:
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

    async def _write_overview_md(self, catalog_dir: Path, job, files, decisions) -> None:
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
