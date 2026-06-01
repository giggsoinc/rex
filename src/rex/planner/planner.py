"""Planner — walks once, segments smart, never calls an LLM.

Speed: 10K files / 5 seconds. Pure os.stat + ext-based grouping.
"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from pathlib import Path

import structlog

from rex.planner.model import (
    Batch,
    BatchFile,
    BatchType,
    ScanPlan,
    SkippedFile,
)
from rex.utils.skip_rules import SkipRules, is_skip_dir, should_skip, SkipReason

logger = structlog.get_logger()


# --- Extension → BatchType mapping ---

EXT_TO_TYPE: dict[str, BatchType] = {}

def _reg(t: BatchType, *exts: str) -> None:
    for e in exts:
        EXT_TO_TYPE[e.lower()] = t

_reg(BatchType.PDF, ".pdf")
_reg(BatchType.OFFICE, ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".odt", ".odp", ".ods")
_reg(BatchType.HTML, ".html", ".htm", ".xhtml")
_reg(BatchType.IMAGE, ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".svg", ".heic", ".heif")
_reg(BatchType.VIDEO, ".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v", ".wmv")
_reg(BatchType.AUDIO, ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus")
_reg(BatchType.ARCHIVE, ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar")
_reg(BatchType.CODE,
     ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".kt", ".go", ".rs", ".c", ".cpp", ".cc",
     ".h", ".hpp", ".rb", ".php", ".swift", ".scala", ".cs", ".sh", ".bash", ".zsh", ".sql",
     ".lua", ".pl", ".pm", ".r", ".m", ".mm")
_reg(BatchType.TEXT_SMALL, ".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".ini", ".toml", ".cfg", ".conf")


def classify_file(path: Path, size_bytes: int) -> BatchType:
    """Pick a BatchType for one file."""
    ext = path.suffix.lower()
    t = EXT_TO_TYPE.get(ext)
    if t is None:
        return BatchType.OTHER
    # Promote text_small → text_large for big text files
    if t == BatchType.TEXT_SMALL and size_bytes > 1024 * 1024:
        return BatchType.TEXT_LARGE
    return t


# --- Per-type cost factors (rough seconds per file at default model) ---

TYPE_SECONDS_PER_FILE: dict[BatchType, float] = {
    BatchType.TEXT_SMALL: 2.0,
    BatchType.TEXT_LARGE: 5.0,
    BatchType.PDF: 8.0,
    BatchType.OFFICE: 6.0,
    BatchType.HTML: 3.0,
    BatchType.IMAGE: 4.0,      # vision call adds time
    BatchType.VIDEO: 1.0,      # just fingerprint
    BatchType.AUDIO: 1.0,      # just fingerprint
    BatchType.CODE: 3.0,
    BatchType.ARCHIVE: 1.0,    # just fingerprint
    BatchType.BINARY: 1.0,
    BatchType.OTHER: 3.0,
}


class Planner:
    """Walks a folder, segments into balanced batches by type/size."""

    def __init__(
        self,
        rules: SkipRules | None = None,
        target_batch_count: int = 4,
        max_files_per_batch: int = 200,
    ) -> None:
        self.rules = rules or SkipRules.default()
        self.target_batch_count = target_batch_count
        self.max_files_per_batch = max_files_per_batch

    async def plan(self, source_path: str, project_name: str) -> ScanPlan:
        """Build a ScanPlan for the source folder.

        Args:
            source_path: Folder to walk.
            project_name: Owning project (for plan provenance).

        Returns:
            ScanPlan with batches + skip list + estimates.
        """
        logger.info("planner_start", source=source_path, project=project_name)

        # 1. Walk + classify (off-thread)
        files, skipped = await asyncio.to_thread(self._walk_classify, source_path)

        # 2. Group by BatchType
        by_type: dict[BatchType, list[tuple[Path, int]]] = defaultdict(list)
        for p, size, t in files:
            by_type[t].append((p, size))

        # 3. Build batches — within each type, split into chunks ≤ max_files_per_batch
        batches: list[Batch] = []
        for t, items in by_type.items():
            # Sort by size descending so large files spread across chunks
            items.sort(key=lambda x: x[1], reverse=True)

            # How many chunks for this type?
            count = len(items)
            chunks = max(1, min(self.target_batch_count, (count + self.max_files_per_batch - 1) // self.max_files_per_batch))
            chunk_size = (count + chunks - 1) // chunks

            for i in range(chunks):
                slice_items = items[i * chunk_size:(i + 1) * chunk_size]
                if not slice_items:
                    continue
                batch_files = [
                    BatchFile(
                        path=str(p),
                        name=p.name,
                        size_bytes=size,
                        extension=p.suffix.lower(),
                    )
                    for p, size in slice_items
                ]
                est = int(sum(TYPE_SECONDS_PER_FILE.get(t, 3.0) for _ in slice_items))
                batches.append(Batch(
                    type=t,
                    files=batch_files,
                    estimated_seconds=est,
                    estimated_tokens=len(slice_items) * 1000,
                ))

        # 4. Files-by-type stats
        files_by_type = {t.value: len(items) for t, items in by_type.items()}

        total_files = sum(len(items) for items in by_type.values())
        total_bytes = sum(s for _, s, _ in files)

        # Time estimate — assume target_batch_count workers in parallel
        max_batch_seconds = max((b.estimated_seconds for b in batches), default=0)
        estimated_seconds = max(60, max_batch_seconds)

        plan = ScanPlan(
            project_name=project_name,
            source_path=str(Path(source_path).resolve()),
            total_files=total_files,
            total_bytes=total_bytes,
            skipped=skipped,
            batches=batches,
            estimated_seconds=estimated_seconds,
            estimated_tokens_in=total_files * 800,
            estimated_tokens_out=total_files * 150,
            files_by_type=files_by_type,
        )
        logger.info(
            "planner_complete",
            files=total_files,
            skipped=len(skipped),
            batches=len(batches),
            est_sec=estimated_seconds,
        )
        return plan

    def _walk_classify(
        self,
        source_path: str,
    ) -> tuple[list[tuple[Path, int, BatchType]], list[SkippedFile]]:
        """Synchronous walk + classify. Off-thread caller."""
        files: list[tuple[Path, int, BatchType]] = []
        skipped: list[SkippedFile] = []
        root = Path(source_path).expanduser().resolve()

        for dirpath, dirnames, filenames in os.walk(root):
            # Prune dirs
            dirnames[:] = [d for d in dirnames if not is_skip_dir(d, self.rules)]
            for filename in filenames:
                fpath = Path(dirpath) / filename
                reason = should_skip(fpath, self.rules)
                if reason != SkipReason.NONE:
                    try:
                        sz = fpath.stat().st_size
                    except OSError:
                        sz = 0
                    skipped.append(SkippedFile(
                        path=str(fpath),
                        reason=reason.value,
                        size_bytes=sz,
                    ))
                    continue
                try:
                    sz = fpath.stat().st_size
                except (PermissionError, OSError):
                    skipped.append(SkippedFile(path=str(fpath), reason="permission_denied", size_bytes=0))
                    continue
                bt = classify_file(fpath, sz)
                files.append((fpath, sz, bt))

        return files, skipped
