"""File-based secret provider — reads .raven/manifest.secrets.json.

For local development ONLY. Production should use a vault.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from rex.secrets.base import SecretNotFoundError, SecretProvider

logger = structlog.get_logger()


class FileSecretProvider(SecretProvider):
    """Reads secrets from a local JSON file.

    File structure (e.g., .raven/manifest.secrets.json):
      {
        "providers": {
          "gemini": {"api_key": "AIza..."},
          "openai": {"api_key": "sk-..."}
        }
      }

    Access via dotted key: "providers.gemini.api_key" -> "AIza..."
    """

    def __init__(self, path: str = ".raven/manifest.secrets.json") -> None:
        super().__init__()
        self.path = Path(path).expanduser().resolve()
        self._data: dict | None = None

    async def _load(self) -> dict:
        """Lazy-load the secrets file."""
        if self._data is not None:
            return self._data
        if not self.path.exists():
            logger.warning("secrets_file_missing", path=str(self.path))
            self._data = {}
            return self._data

        def _read():
            return json.loads(self.path.read_text())

        self._data = await asyncio.to_thread(_read)
        return self._data

    async def _fetch(self, key: str) -> str:
        """Fetch using dotted key (e.g., 'providers.gemini.api_key')."""
        data = await self._load()
        parts = key.split(".")
        node = data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                raise SecretNotFoundError(f"Key not found in {self.path}: {key}")
            node = node[part]
        if not isinstance(node, str):
            raise SecretNotFoundError(f"Key {key} is not a string value")
        return node

    async def health_check(self) -> bool:
        """Verify file exists and is valid JSON."""
        try:
            data = await self._load()
            return isinstance(data, dict)
        except Exception as e:
            logger.error("file_secret_provider_health_failed", path=str(self.path), error=str(e))
            return False
