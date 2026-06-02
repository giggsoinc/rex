"""Local filesystem storage plugin — Phase 1 default."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import AsyncIterator

from rex.plugins.base import FileEntry, StoragePlugin


class LocalFSPlugin(StoragePlugin):
    """Local filesystem storage — walks directories, reads/writes files."""

    async def walk(self, path: str) -> AsyncIterator[FileEntry]:
        """Walk a local directory tree, yielding one file at a time.

        Runs os.walk in a thread to avoid blocking the async event loop.
        Applies SkipRules — hidden dirs, junk files, oversized files all dropped.
        """
        from rex.utils.skip_rules import SkipRules, is_skip_dir, should_skip, SkipReason

        rules = SkipRules.default()
        root = Path(path).resolve()

        def _walk_sync():
            """Synchronous walk — runs in thread pool."""
            entries = []
            for dirpath, dirnames, filenames in os.walk(root):
                # Skip hidden and junk directories
                dirnames[:] = [d for d in dirnames if not is_skip_dir(d, rules)]

                for filename in filenames:
                    filepath = Path(dirpath) / filename
                    # Skip rules: filename patterns, size limits, binaries
                    if should_skip(filepath, rules) != SkipReason.NONE:
                        continue
                    try:
                        stat = filepath.stat()
                        entries.append(FileEntry(
                            path=str(filepath),
                            name=filename,
                            size_bytes=stat.st_size,
                            is_dir=False,
                        ))
                    except (PermissionError, OSError):
                        continue
            return entries

        # Run blocking I/O in thread pool
        entries = await asyncio.to_thread(_walk_sync)
        for entry in entries:
            yield entry

    async def read_bytes(self, path: str) -> bytes:
        """Read file bytes in a thread."""
        return await asyncio.to_thread(Path(path).read_bytes)

    async def write_bytes(self, path: str, data: bytes) -> None:
        """Write bytes to file in a thread."""
        p = Path(path)
        await asyncio.to_thread(p.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(p.write_bytes, data)

    async def copy(self, src: str, dst: str) -> None:
        """Copy file from source to destination."""
        dst_path = Path(dst)
        await asyncio.to_thread(dst_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, src, dst)

    async def exists(self, path: str) -> bool:
        """Check if path exists."""
        return await asyncio.to_thread(Path(path).exists)

    async def mkdir(self, path: str) -> None:
        """Create directory and parents."""
        await asyncio.to_thread(Path(path).mkdir, parents=True, exist_ok=True)
