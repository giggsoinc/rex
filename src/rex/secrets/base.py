"""SecretProvider abstract interface — every secret backend implements this."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class SecretNotFoundError(KeyError):
    """Raised when a requested secret key is not found in the backend."""


@dataclass
class CachedSecret:
    """A cached secret value with TTL."""

    value: str
    fetched_at: float
    ttl_seconds: int = 3600  # 1 hour default

    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return (time.time() - self.fetched_at) > self.ttl_seconds


class SecretProvider(ABC):
    """Abstract secret provider — fetches credentials from a backend.

    Implementations:
      FileSecretProvider          dev: .raven/manifest.secrets.json
      EnvVarProvider              k8s / docker / env-mounted secrets
      AwsSecretsManagerProvider   AWS Secrets Manager
      AwsSsmParameterStoreProvider AWS Systems Manager Parameter Store
      AzureKeyVaultProvider       Azure Key Vault
      GcpSecretManagerProvider    GCP Secret Manager
      OciVaultProvider            Oracle OCI Vault
      HashiCorpVaultProvider      HashiCorp Vault

    All callers do: provider.get("gemini.api_key").
    Caching, audit logging, and TTL refresh are handled by the base.
    """

    cache_ttl_seconds: int = 3600

    def __init__(self) -> None:
        self._cache: dict[str, CachedSecret] = {}
        self._audit_log: list[dict] = []

    @abstractmethod
    async def _fetch(self, key: str) -> str:
        """Backend-specific fetch. Raise SecretNotFoundError if missing.

        Args:
            key: Dotted key (e.g., "gemini.api_key", "aws.access_key").

        Returns:
            Secret string value.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify the backend is reachable and we have permission to read."""
        ...

    async def get(self, key: str, *, refresh: bool = False) -> str:
        """Fetch a secret, with caching.

        Args:
            key: Dotted secret key (e.g., "gemini.api_key").
            refresh: Force re-fetch even if cached.

        Returns:
            Secret value.

        Raises:
            SecretNotFoundError: If key doesn't exist in backend.
        """
        # Check cache
        if not refresh:
            cached = self._cache.get(key)
            if cached and not cached.is_expired():
                self._log_access(key, source="cache", hit=True)
                return cached.value

        # Fetch from backend
        value = await self._fetch(key)
        self._cache[key] = CachedSecret(
            value=value,
            fetched_at=time.time(),
            ttl_seconds=self.cache_ttl_seconds,
        )
        self._log_access(key, source=self.__class__.__name__, hit=False)
        return value

    async def get_optional(self, key: str, default: str = "") -> str:
        """Get a secret, returning default if not found (no exception)."""
        try:
            return await self.get(key)
        except SecretNotFoundError:
            return default

    def invalidate(self, key: str | None = None) -> None:
        """Invalidate cache for one key, or all keys if None."""
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

    def get_audit_log(self) -> list[dict]:
        """Return the audit log of secret accesses (for SOC2/compliance)."""
        return list(self._audit_log)

    def _log_access(self, key: str, source: str, hit: bool) -> None:
        """Append to audit log. Never logs secret values, only keys + source."""
        self._audit_log.append(
            {
                "key": key,
                "source": source,
                "cache_hit": hit,
                "timestamp": time.time(),
            }
        )
        # Truncate to prevent unbounded growth
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]
