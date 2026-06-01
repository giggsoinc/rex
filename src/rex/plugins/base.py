"""Storage plugin interface — all input/output sources implement this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator


@dataclass
class FileEntry:
    """A file discovered by a storage plugin."""

    path: str
    name: str
    size_bytes: int
    is_dir: bool = False


class StoragePlugin(ABC):
    """Base class for all storage plugins.

    Implement this to add new input sources (S3, Google Drive, etc.)
    or output destinations.
    """

    @abstractmethod
    async def walk(self, path: str) -> AsyncIterator[FileEntry]:
        """Walk a directory and yield file entries one at a time.

        Args:
            path: Root path to walk.

        Yields:
            FileEntry for each file found (not directories).
        """
        ...

    @abstractmethod
    async def read_bytes(self, path: str) -> bytes:
        """Read file content as bytes.

        Args:
            path: Path to file.

        Returns:
            File content as bytes.
        """
        ...

    @abstractmethod
    async def write_bytes(self, path: str, data: bytes) -> None:
        """Write bytes to a file.

        Args:
            path: Destination path.
            data: Content to write.
        """
        ...

    @abstractmethod
    async def copy(self, src: str, dst: str) -> None:
        """Copy a file from source to destination.

        Args:
            src: Source path.
            dst: Destination path.
        """
        ...

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check if a path exists.

        Args:
            path: Path to check.

        Returns:
            True if exists.
        """
        ...

    @abstractmethod
    async def mkdir(self, path: str) -> None:
        """Create directory (and parents).

        Args:
            path: Directory path to create.
        """
        ...
