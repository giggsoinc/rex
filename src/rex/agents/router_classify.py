"""Default-category heuristics + dedup detection mixin for LLMRouter.

Extracted from router_logic.py to keep modules under the line limit. The
mixin expects the host class to provide: self.settings.
"""

from __future__ import annotations

from rex.agents.router_dedup import _DedupResult
from rex.models.schemas import DedupStatus, FileContext


class RouterClassifyMixin:
    """Heuristic category inference and deterministic dedup checks."""

    @staticmethod
    def _infer_default_category(context: FileContext) -> str:
        """Heuristic category if router can't decide."""
        rec = context.file_record
        ext = rec.extension.lower()
        if ext in {".pdf", ".doc", ".docx", ".odt", ".rtf"}:
            return "Documents"
        if ext in {".ppt", ".pptx", ".odp"}:
            return "Presentations"
        if ext in {".xls", ".xlsx", ".ods", ".csv"}:
            return "Spreadsheets"
        if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
            return "Images"
        if ext in {".mp4", ".mov", ".avi", ".mkv"}:
            return "Videos"
        if ext in {".mp3", ".wav", ".flac"}:
            return "Audio"
        if ext in {".md", ".txt", ".rst"}:
            return "Notes"
        if ext in {".py", ".js", ".ts", ".go", ".java"}:
            return "Code"
        if ext in {".zip", ".tar", ".gz", ".7z"}:
            return "Archives"
        return "Other"

    def _check_dedup(self, context: FileContext) -> _DedupResult | None:
        """Examine neighbors for exact/near duplicates.

        Returns None if no dedup signal; else a _DedupResult.
        """
        near_threshold = self.settings.dedup_near_threshold
        related_threshold = self.settings.dedup_related_threshold

        for n in context.similar_files:
            if n.similarity_score >= 0.9999:
                # Treat ≥0.9999 as exact (same hash would yield 1.0)
                return _DedupResult(
                    status=DedupStatus.EXACT_DUPLICATE,
                    duplicate_of=n.file_id,
                    similarity=n.similarity_score,
                )
            if n.similarity_score >= near_threshold:
                return _DedupResult(
                    status=DedupStatus.NEAR_DUPLICATE,
                    duplicate_of=n.file_id,
                    similarity=n.similarity_score,
                )
            if n.similarity_score >= related_threshold:
                return _DedupResult(
                    status=DedupStatus.RELATED,
                    duplicate_of=n.file_id,
                    similarity=n.similarity_score,
                )
            break  # only check top neighbor for dedup classification
        return None
