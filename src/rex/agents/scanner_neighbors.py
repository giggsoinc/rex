"""Neighbor lookup, category collection, and EXIF helpers for LocalScanner.

Extracted from scanner_process.py to keep modules under the line limit. The
mixin expects the host class to provide: self.vectors, self.jobs.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from rex.models.schemas import SimilarFile

logger = structlog.get_logger()


class ScannerNeighborsMixin:
    """Vector-neighbor, category, and EXIF helpers for LocalScanner."""

    async def _find_similar(
        self,
        exclude_file_id: str,
        query_vector: list[float] | None = None,
        top_k: int = 3,
    ) -> list[SimilarFile]:
        """Top-k vector neighbors, excluding self."""
        if not query_vector:
            return []
        try:
            matches = await self.vectors.search(query_vector, top_k=top_k + 1)
        except Exception as e:
            logger.warning("vector_search_failed", error=str(e))
            return []
        out = []
        for m in matches:
            if m.file_id == exclude_file_id:
                continue
            out.append(
                SimilarFile(
                    file_id=m.file_id,
                    filename=m.metadata.get("filename", ""),
                    similarity_score=m.similarity_score,
                )
            )
            if len(out) >= top_k:
                break
        return out

    async def _collect_existing_categories(self, job_id: str) -> list[str]:
        """Distinct categories assigned so far this job."""
        decisions = await self.jobs.list_decisions(job_id)
        cats = {d.category for d in decisions.values() if d.category}
        return sorted(cats)

    def _read_exif(self, path: Path) -> dict | None:
        """Best-effort EXIF read using Pillow."""
        try:
            from PIL import Image
            img = Image.open(path)
            exif = getattr(img, "_getexif", lambda: None)()
            if not exif:
                return None
            # Return safe subset
            return {str(k): str(v)[:200] for k, v in exif.items()}
        except Exception:
            return None
