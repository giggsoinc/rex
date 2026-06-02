"""Scanner agent — walks a folder, extracts text, fingerprints, embeds.

Streams FileContext objects downstream. Never buffers the whole directory.
Errors per-file are logged and skipped; the agent never dies mid-scan.
"""

from __future__ import annotations

from typing import AsyncIterator

import structlog

from rex.agents.scanner_extract import (
    extract_text,
    file_timestamps,
    sha256_of_file,
)
from rex.agents.scanner_meta import (
    detect_media_type,
    detect_mime,
)
from rex.agents.scanner_neighbors import ScannerNeighborsMixin
from rex.agents.scanner_process import ScannerProcessMixin
from rex.config import Settings, get_settings
from rex.ml.provider import ModelProvider
from rex.ml.vision import VisionEngine
from rex.models.schemas import FileContext
from rex.orchestrator.state import JobStore
from rex.plugins.local_fs import LocalFSPlugin
from rex.vectorstore import VectorStore

logger = structlog.get_logger()

# Re-exported for backward-compatible public API.
__all__ = [
    "LocalScanner",
    "detect_media_type",
    "detect_mime",
    "extract_text",
    "file_timestamps",
    "sha256_of_file",
]


# --- Scanner Agent ---

class LocalScanner(ScannerProcessMixin, ScannerNeighborsMixin):
    """Scanner agent implementation for local filesystem.

    Walks via LocalFSPlugin. Hashes, extracts, embeds, stores.
    Yields FileContext for downstream stages.
    """

    def __init__(
        self,
        model_provider: ModelProvider,
        vision_engine: VisionEngine,
        vector_store: VectorStore,
        job_store: JobStore,
        settings: Settings | None = None,
    ) -> None:
        self.model = model_provider
        self.vision = vision_engine
        self.vectors = vector_store
        self.jobs = job_store
        self.settings = settings or get_settings()
        self.fs = LocalFSPlugin()

    async def estimate_count(self, source_path: str) -> int:
        """Quick file count for progress reporting."""
        count = 0
        async for _ in self.fs.walk(source_path):
            count += 1
        return count

    async def scan(self, source_path: str, job_id: str) -> AsyncIterator[FileContext]:
        """Walk source_path, yield FileContext per file."""
        async for entry in self.fs.walk(source_path):
            try:
                ctx = await self._process_one(entry.path, job_id)
                if ctx is not None:
                    yield ctx
            except Exception as e:
                logger.error("scanner_file_failed", path=entry.path, error=str(e))
                # Continue — never let one file kill the scan
