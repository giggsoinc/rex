"""AWS Secrets Manager provider.

Auth: uses default AWS credential chain (IAM Task Role on Fargate,
Instance Profile on EC2, env vars locally).
"""

from __future__ import annotations

import asyncio
import json

import structlog

from rex.secrets.base import SecretNotFoundError, SecretProvider

logger = structlog.get_logger()


class AwsSecretsManagerProvider(SecretProvider):
    """AWS Secrets Manager — production-grade secret storage.

    Secret naming convention:
      Prefix: /rex/prod/  (configurable)
      Full secret name: /rex/prod/gemini  (one secret per provider)
      Value: JSON blob {"api_key": "..."}

    Access via dotted key: "gemini.api_key"
      -> fetches secret "/rex/prod/gemini"
      -> parses JSON
      -> returns ["api_key"]
    """

    def __init__(
        self,
        prefix: str = "/rex/prod/",
        region: str = "us-east-1",
    ) -> None:
        super().__init__()
        self.prefix = prefix
        self.region = region
        self._client = None

    def _get_client(self):
        """Lazy init boto3 client."""
        if self._client is None:
            import boto3
            self._client = boto3.client("secretsmanager", region_name=self.region)
        return self._client

    async def _fetch(self, key: str) -> str:
        """Fetch secret. Key 'gemini.api_key' -> secret 'prefix/gemini' -> field 'api_key'."""
        parts = key.split(".", 1)
        if len(parts) != 2:
            raise SecretNotFoundError(f"Key must be 'provider.field' format: {key}")

        provider, field = parts
        secret_name = f"{self.prefix}{provider}"

        def _do_fetch():
            client = self._get_client()
            try:
                response = client.get_secret_value(SecretId=secret_name)
            except client.exceptions.ResourceNotFoundException:
                raise SecretNotFoundError(f"Secret {secret_name} not found")
            return response["SecretString"]

        try:
            secret_string = await asyncio.to_thread(_do_fetch)
        except SecretNotFoundError:
            raise
        except Exception as e:
            logger.error("aws_secrets_manager_fetch_failed", secret=secret_name, error=str(e))
            raise SecretNotFoundError(f"Failed to fetch {secret_name}: {e}") from e

        try:
            data = json.loads(secret_string)
        except json.JSONDecodeError:
            # Plain string secret
            if field == "value":
                return secret_string
            raise SecretNotFoundError(f"Secret {secret_name} not JSON")

        if field not in data:
            raise SecretNotFoundError(f"Field {field} not in secret {secret_name}")
        return data[field]

    async def health_check(self) -> bool:
        """List secrets with our prefix — verify auth + reachability."""
        def _do_check():
            client = self._get_client()
            client.list_secrets(MaxResults=1)
            return True

        try:
            return await asyncio.to_thread(_do_check)
        except Exception as e:
            logger.error("aws_secrets_manager_health_failed", error=str(e))
            return False
