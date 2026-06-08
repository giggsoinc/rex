"""Sort engine — Phase-1 file placement using business context + type taxonomy.

Two-phase architecture (UX-single-flow):
  Scan → Route → SortEngine (Phase 1) || GraphRAG (Phase 2)
                       │
                       ▼
                 AWAITING_REVIEW gate → SERVE

The SortEngine:
  1. Aligns the router's free-form category to the user's BusinessContext domains
     (snaps to nearest declared domain; falls back to _Unsorted/ if no match).
  2. Maps the file's extension into a 12-bucket type taxonomy.
  3. Routes low-confidence files to /_Review/ for HITL triage.
  4. Routes destructive actions (TRASH) to /_Trash/ — never modifies source.
  5. Lazy folder creation — only writes subfolders that have content.

Split across four modules to honor the 150-line-per-file Raven style guard:
  - sort_engine.py            — SortEngine class (this file)
  - sort_engine_taxonomy.py   — extension buckets + path safety
  - sort_engine_routing.py    — pure resolve_destination + SortDecision
  - sort_engine_index.py      — write_index INDEX.md generator
"""

from __future__ import annotations

from pathlib import Path

import structlog

from rex.agents.sort_engine_index import write_index
from rex.agents.sort_engine_routing import SortDecision, resolve_destination
from rex.agents.sort_engine_taxonomy import extension_to_bucket, safe_segment
from rex.agents.version_detector import SupersessionInfo
from rex.models.business_context import BusinessContext
from rex.models.schemas import DedupStatus, FileDecision, FileRecord
from rex.plugins.local_fs import LocalFSPlugin

logger = structlog.get_logger()

__all__ = [
    "SortEngine",
    "SortDecision",
    "resolve_destination",
    "extension_to_bucket",
    "safe_segment",
]


class SortEngine:
    """Phase-1 file placement — copies files and emits root INDEX.md.

    Pluggable backend via LocalFSPlugin (extensible to S3 / GCS later).
    Idempotent: copy is skipped if destination already exists with same size.
    """

    def __init__(
        self,
        fs: LocalFSPlugin | None = None,
        version_map: dict[str, SupersessionInfo] | None = None,
    ) -> None:
        """Construct the sort engine.

        Args:
            fs: optional injected FS plugin.
            version_map: optional {file_id: SupersessionInfo} from version_detector;
                files in the map are routed to _Stale/ regardless of router decision.
        """
        self.fs = fs or LocalFSPlugin()
        self.version_map = version_map or {}
        # Track placements for INDEX.md
        self._placements: list[tuple[FileRecord, FileDecision, SortDecision]] = []

    async def place(
        self,
        file_record: FileRecord,
        decision: FileDecision,
        context: BusinessContext,
        output_root: str | Path,
    ) -> SortDecision:
        """Resolve destination and copy the file. Returns the SortDecision."""
        out_root = Path(output_root).expanduser().resolve()
        # Apply version supersession overlay BEFORE routing
        if file_record.id in self.version_map:
            info = self.version_map[file_record.id]
            decision = decision.model_copy(update={
                "dedup_status": DedupStatus.SUPERSEDED,
                "duplicate_of": info.superseded_by,
                "reasoning": (
                    f"Superseded by V{info.canonical_version} "
                    f"(this is V{info.own_version}); " + decision.reasoning
                ),
            })
        sort = resolve_destination(file_record, decision, context, out_root)

        sort.destination.parent.mkdir(parents=True, exist_ok=True)

        # Skip copy if already in place with same size (idempotent)
        if sort.destination.exists():
            try:
                if sort.destination.stat().st_size == file_record.size_bytes:
                    self._placements.append((file_record, decision, sort))
                    return sort
            except OSError:
                pass
            # Different file with same name — suffix with short hash
            stem = sort.destination.stem
            suffix = sort.destination.suffix
            short_hash = file_record.sha256_hash[:8]
            sort.destination = sort.destination.parent / f"{stem}__{short_hash}{suffix}"

        try:
            await self.fs.copy(file_record.original_path, str(sort.destination))
        except Exception as e:
            logger.error(
                "sort_copy_failed",
                src=file_record.original_path,
                dst=str(sort.destination),
                error=str(e),
            )
            raise

        self._placements.append((file_record, decision, sort))
        return sort

    def write_index(self, output_root: str | Path, context: BusinessContext) -> Path:
        """Write a human + Obsidian-friendly INDEX.md at the output root."""
        return write_index(output_root, context, self._placements)

    @property
    def placements(self) -> list[tuple[FileRecord, FileDecision, SortDecision]]:
        """Read-only view of recorded placements (for inspection / tests)."""
        return list(self._placements)
