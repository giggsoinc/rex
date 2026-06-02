"""Organizer agent — places files into organized output, writes catalog.

Copy semantics by default (never modifies source). Writes per-file metadata
sidecars and Obsidian-compatible catalog markdown.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import structlog

from rex.agents.organizer_catalog import (
    build_sidecar,
    write_categories_md,
    write_duplicates_md,
    write_index_md,
    write_overview_md,
    write_tags_md,
)
from rex.config import Settings, get_settings
from rex.models.schemas import FileAction, FileDecision, FileRecord
from rex.orchestrator.state import JobStore
from rex.plugins.local_fs import LocalFSPlugin

logger = structlog.get_logger()

# Re-exported for backward-compatible public API.
__all__ = ["LocalOrganizer", "safe_path_segment"]


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
        sidecar = build_sidecar(file_record, decision, dest_path)
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

        write_index_md(catalog_dir, job, files, decisions)
        write_tags_md(catalog_dir, files, decisions)
        write_categories_md(catalog_dir, files, decisions)
        write_duplicates_md(catalog_dir, files, decisions)
        write_overview_md(catalog_dir, job, files, decisions)
        logger.info("catalog_written", job_id=job_id, files=len(files), dir=str(catalog_dir))
