"""Azure Key Vault provider.

Auth: DefaultAzureCredential — Managed Identity in prod, az CLI in dev.
"""

from __future__ import annotations

import asyncio

import structlog

from rex.secrets.base import SecretNotFoundError, SecretProvider

logger = structlog.get_logger()


class AzureKeyVaultProvider(SecretProvider):
    """Azure Key Vault secret provider.

    Secret naming: rex-prod-gemini-api-key (no dots/slashes in Azure)
    Dotted key 'gemini.api_key' -> secret name 'rex-prod-gemini-api-key'.
    """

    def __init__(self, vault_url: str, prefix: str = "rex-prod-") -> None:
        super().__init__()
        self.vault_url = vault_url
        self.prefix = prefix
        self._client = None

    def _get_client(self):
        """Lazy init Azure Key Vault client."""
        if self._client is None:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient
            credential = DefaultAzureCredential()
            self._client = SecretClient(vault_url=self.vault_url, credential=credential)
        return self._client

    @staticmethod
    def _key_to_secret_name(key: str, prefix: str) -> str:
        """Convert 'gemini.api_key' -> 'rex-prod-gemini-api-key'."""
        return prefix + key.replace(".", "-").replace("_", "-")

    async def _fetch(self, key: str) -> str:
        secret_name = self._key_to_secret_name(key, self.prefix)

        def _do_fetch():
            client = self._get_client()
            try:
                secret = client.get_secret(secret_name)
                return secret.value
            except Exception as e:
                if "SecretNotFound" in str(e):
                    raise SecretNotFoundError(f"Secret {secret_name} not found in Azure KV")
                raise

        try:
            return await asyncio.to_thread(_do_fetch)
        except SecretNotFoundError:
            raise
        except Exception as e:
            logger.error("azure_keyvault_fetch_failed", secret=secret_name, error=str(e))
            raise SecretNotFoundError(f"Failed to fetch {secret_name}: {e}") from e

    async def health_check(self) -> bool:
        def _do_check():
            client = self._get_client()
            list(client.list_properties_of_secrets(max_page_size=1))
            return True

        try:
            return await asyncio.to_thread(_do_check)
        except Exception as e:
            logger.error("azure_keyvault_health_failed", error=str(e))
            return False
