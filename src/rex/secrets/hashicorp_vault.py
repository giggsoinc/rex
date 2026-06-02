"""HashiCorp Vault provider — on-prem secret management.

Auth: AppRole, Kubernetes auth, or VAULT_TOKEN env var.
"""

from __future__ import annotations

import asyncio

import structlog

from rex.secrets.base import SecretNotFoundError, SecretProvider

logger = structlog.get_logger()


class HashiCorpVaultProvider(SecretProvider):
    """HashiCorp Vault using KV v2 engine.

    Path naming: secret/data/rex/prod/gemini
      -> read returns {"data": {"api_key": "..."}}

    Dotted key 'gemini.api_key' -> reads 'secret/data/<prefix>gemini'
      -> returns ["data"]["api_key"]
    """

    def __init__(
        self,
        vault_url: str,
        token: str | None = None,
        prefix: str = "rex/prod/",
        mount_point: str = "secret",
    ) -> None:
        super().__init__()
        self.vault_url = vault_url
        self.token = token
        self.prefix = prefix.strip("/") + "/"
        self.mount_point = mount_point
        self._client = None

    def _get_client(self):
        """Lazy init hvac client."""
        if self._client is None:
            import hvac
            self._client = hvac.Client(url=self.vault_url, token=self.token)
            if not self._client.is_authenticated():
                # Try Kubernetes auth if running in-cluster
                self._try_k8s_auth()
        return self._client

    def _try_k8s_auth(self):
        """Attempt Kubernetes auth in-cluster."""
        try:
            with open("/var/run/secrets/kubernetes.io/serviceaccount/token") as f:
                jwt = f.read()
            self._client.auth.kubernetes.login(role="rex", jwt=jwt)
        except Exception as e:
            logger.warning("vault_k8s_auth_failed", error=str(e))

    async def _fetch(self, key: str) -> str:
        parts = key.split(".", 1)
        if len(parts) != 2:
            raise SecretNotFoundError(f"Key must be 'provider.field': {key}")

        provider, field = parts
        path = f"{self.prefix}{provider}"

        def _do_fetch():
            client = self._get_client()
            try:
                response = client.secrets.kv.v2.read_secret_version(
                    path=path, mount_point=self.mount_point,
                )
                data = response["data"]["data"]
            except Exception as e:
                if "InvalidPath" in str(e) or "404" in str(e):
                    raise SecretNotFoundError(f"Path {path} not found in Vault")
                raise

            if field not in data:
                raise SecretNotFoundError(f"Field {field} not in {path}")
            return data[field]

        try:
            return await asyncio.to_thread(_do_fetch)
        except SecretNotFoundError:
            raise
        except Exception as e:
            logger.error("vault_fetch_failed", path=path, error=str(e))
            raise SecretNotFoundError(f"Failed to fetch {path}: {e}") from e

    async def health_check(self) -> bool:
        def _do_check():
            client = self._get_client()
            return client.sys.is_initialized() and not client.sys.is_sealed()

        try:
            return await asyncio.to_thread(_do_check)
        except Exception as e:
            logger.error("vault_health_failed", error=str(e))
            return False
