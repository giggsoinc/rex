"""Oracle Cloud Infrastructure (OCI) Vault provider.

Auth: Instance Principal in OCI compute, config file locally.
"""

from __future__ import annotations

import asyncio
import base64

import structlog

from rex.secrets.base import SecretNotFoundError, SecretProvider

logger = structlog.get_logger()


class OciVaultProvider(SecretProvider):
    """Oracle OCI Vault secret provider.

    Secrets are referenced by name within a vault.
    Naming convention: rex_prod_gemini_api_key
    """

    def __init__(
        self,
        vault_id: str,
        compartment_id: str,
        prefix: str = "rex_prod_",
    ) -> None:
        super().__init__()
        self.vault_id = vault_id
        self.compartment_id = compartment_id
        self.prefix = prefix
        self._client = None
        self._secrets_client = None
        self._secret_id_cache: dict[str, str] = {}

    def _get_clients(self):
        """Lazy init OCI clients."""
        if self._client is None:
            import oci
            try:
                # Try Instance Principal (in OCI compute)
                signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
                self._client = oci.vault.VaultsClient(config={}, signer=signer)
                self._secrets_client = oci.secrets.SecretsClient(config={}, signer=signer)
            except Exception:
                # Fall back to config file
                config = oci.config.from_file()
                self._client = oci.vault.VaultsClient(config)
                self._secrets_client = oci.secrets.SecretsClient(config)
        return self._client, self._secrets_client

    @staticmethod
    def _key_to_secret_name(key: str, prefix: str) -> str:
        """Convert 'gemini.api_key' -> 'rex_prod_gemini_api_key'."""
        return prefix + key.replace(".", "_")

    async def _fetch(self, key: str) -> str:
        secret_name = self._key_to_secret_name(key, self.prefix)

        def _do_fetch():
            client, secrets_client = self._get_clients()
            # Find secret OCID (cache it)
            if secret_name in self._secret_id_cache:
                secret_id = self._secret_id_cache[secret_name]
            else:
                secrets = client.list_secrets(
                    compartment_id=self.compartment_id,
                    name=secret_name,
                ).data
                if not secrets:
                    raise SecretNotFoundError(f"Secret {secret_name} not in OCI Vault")
                secret_id = secrets[0].id
                self._secret_id_cache[secret_name] = secret_id

            bundle = secrets_client.get_secret_bundle(secret_id=secret_id).data
            content = bundle.secret_bundle_content.content
            return base64.b64decode(content).decode("utf-8")

        try:
            return await asyncio.to_thread(_do_fetch)
        except SecretNotFoundError:
            raise
        except Exception as e:
            logger.error("oci_vault_fetch_failed", secret=secret_name, error=str(e))
            raise SecretNotFoundError(f"Failed to fetch {secret_name}: {e}") from e

    async def health_check(self) -> bool:
        def _do_check():
            client, _ = self._get_clients()
            client.list_secrets(compartment_id=self.compartment_id, limit=1)
            return True

        try:
            return await asyncio.to_thread(_do_check)
        except Exception as e:
            logger.error("oci_vault_health_failed", error=str(e))
            return False
