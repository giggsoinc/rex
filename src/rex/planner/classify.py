"""Classification helpers — extension mapping + per-type cost factors.

Pure data + a couple of small functions. No I/O, no LLM.
"""

from __future__ import annotations

from pathlib import Path

from rex.planner.model import Batch, BatchFile, BatchType


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


def build_batches(
    by_type: dict[BatchType, list[tuple[Path, int]]],
    target_batch_count: int,
    max_files_per_batch: int,
) -> list[Batch]:
    """Split each type's files into balanced chunks ≤ max_files_per_batch."""
    batches: list[Batch] = []
    for t, items in by_type.items():
        # Sort by size descending so large files spread across chunks
        items.sort(key=lambda x: x[1], reverse=True)

        # How many chunks for this type?
        count = len(items)
        chunks = max(1, min(target_batch_count, (count + max_files_per_batch - 1) // max_files_per_batch))
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
    return batches
