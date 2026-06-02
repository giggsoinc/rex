"""Agent contracts — the typed interface between Scanner, Router, Organizer.

Every agent is an async callable that takes a typed input and returns a typed output.
This file defines the protocols — agents are pluggable as long as they match.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol

from rex.models.schemas import FileContext, FileDecision, FileRecord


class ScannerAgent(Protocol):
    """Scanner: walks a folder, yields file records + contexts.

    Implementations: rex.agents.scanner.LocalScanner
    """

    async def scan(self, source_path: str, job_id: str) -> AsyncIterator[FileContext]:
        """Walk source_path, yield FileContext one at a time.

        Args:
            source_path: Root directory to scan.
            job_id: Job tracking ID.

        Yields:
            FileContext for each file (with embedding + metadata).
        """
        ...

    async def estimate_count(self, source_path: str) -> int:
        """Rough count of files for progress reporting."""
        ...


class RouterAgent(Protocol):
    """Router: classifies a file, decides action, marks duplicates.

    Implementations: rex.agents.router.LLMRouter
    """

    async def route(self, context: FileContext) -> FileDecision:
        """Classify and decide action for one file.

        Args:
            context: Enriched file context with embedding + neighbors.

        Returns:
            FileDecision with category, tags, action, dedup status, reasoning.
        """
        ...


class OrganizerAgent(Protocol):
    """Organizer: moves files into organized structure, writes catalog.

    Implementations: rex.agents.organizer.LocalOrganizer
    """

    async def organize(
        self,
        file_record: FileRecord,
        decision: FileDecision,
        output_root: str,
    ) -> str:
        """Place a file according to its decision.

        Args:
            file_record: Original file.
            decision: Router's decision.
            output_root: Root of organized output.

        Returns:
            New path where file was placed (or "" if action was 'trash' and skipped).
        """
        ...

    async def finalize(self, job_id: str, output_root: str) -> None:
        """Build catalog (index.md, tags.md, categories.md) after all files done."""
        ...
