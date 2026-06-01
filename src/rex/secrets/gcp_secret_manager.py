"""GCP Secret Manager provider.

Auth: Application Default Credentials (Workload Identity on GKE, gcloud locally).
"""

from __future__ import annotations

import asyncio

import structlog

from rex.secrets.base import SecretNotFoundError, SecretProvider

logger = structlog.get_logger()


class GcpSecretManagerProvider(SecretProvider):
    """GCP Secret Manager.

    Secret naming: projects/<project>/secrets/<name>/versions/latest
    Name convention: rex-prod-gemini-api-key
    """

    def __init__(self, project_id: str, prefix: str = "rex-prod-") -> None:
        super().__init__()
        self.project_id = project_id
        self.prefix = prefix
        self._client = None

    def _get_client(self):
        """Lazy init GCP Secret Manager client."""
        if self._client is None:
            from google.cloud import secretmanager
            self._client = secretmanager.SecretManagerServiceClient()
        return self._client

    @staticmethod
    def _key_to_secret_name(key: str, prefix: str) -> str:
        """Convert 'gemini.api_key' -> 'rex-prod-gemini-api-key'."""
        return prefix + key.replace(".", "-").replace("_", "-")

    async def _fetch(self, key: str) -> str:
        secret_name = self._key_to_secret_name(key, self.prefix)
        full_path = f"projects/{self.project_id}/secrets/{secret_name}/versions/latest"

        def _do_fetch():
            client = self._get_client()
            try:
                response = client.access_secret_version(name=full_path)
                return response.payload.data.decode("UTF-8")
            except Exception as e:
                if "NotFound" in str(e) or "not found" in str(e).lower():
                    raise SecretNotFoundError(f"Secret {secret_name} not found in GCP SM")
                raise

        try:
            return await asyncio.to_thread(_do_fetch)
        except SecretNotFoundError:
            raise
        except Exception as e:
            logger.error("gcp_secret_manager_fetch_failed", secret=secret_name, error=str(e))
            raise SecretNotFoundError(f"Failed to fetch {secret_name}: {e}") from e

    async def health_check(self) -> bool:
        def _do_check():
            client = self._get_client()
            parent = f"projects/{self.project_id}"
            list(client.list_secrets(request={"parent": parent, "page_size": 1}))
            return True

        try:
            return await asyncio.to_thread(_do_check)
        except Exception as e:
            logger.error("gcp_secret_manager_health_failed", error=str(e))
            return False
