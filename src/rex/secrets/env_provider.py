"""Environment-variable secret provider — for k8s/Docker mounted secrets.

Converts dotted keys to upper-snake env var names:
  "providers.gemini.api_key" -> "REX_PROVIDERS_GEMINI_API_KEY"
  "gemini.api_key"           -> "REX_GEMINI_API_KEY"

Kubernetes ConfigMaps + Secrets typically mount as env vars.
"""

from __future__ import annotations

import os

import structlog

from rex.secrets.base import SecretNotFoundError, SecretProvider

logger = structlog.get_logger()


class EnvVarProvider(SecretProvider):
    """Reads secrets from environment variables.

    Used in k8s where Secrets are mounted as env vars,
    or in CI/CD where GitHub Actions / GitLab CI inject env vars.
    """

    def __init__(self, prefix: str = "REX_") -> None:
        super().__init__()
        self.prefix = prefix

    @staticmethod
    def _key_to_env(key: str, prefix: str) -> str:
        """Convert 'gemini.api_key' -> 'REX_GEMINI_API_KEY'."""
        env_key = key.replace(".", "_").upper()
        return f"{prefix}{env_key}"

    async def _fetch(self, key: str) -> str:
        env_key = self._key_to_env(key, self.prefix)
        value = os.environ.get(env_key)
        if value is None:
            raise SecretNotFoundError(f"Env var {env_key} not set for key {key}")
        return value

    async def health_check(self) -> bool:
        """Always healthy — env vars are read-only."""
        return True
