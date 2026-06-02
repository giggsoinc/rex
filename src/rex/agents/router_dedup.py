"""Dedup result container for the LLM router.

Extracted from router.py to keep modules under the line limit.
"""

from __future__ import annotations

from rex.models.schemas import DedupStatus


class _DedupResult:
    __slots__ = ("status", "duplicate_of", "similarity")

    def __init__(self, status: DedupStatus, duplicate_of: str, similarity: float) -> None:
        self.status = status
        self.duplicate_of = duplicate_of
        self.similarity = similarity
