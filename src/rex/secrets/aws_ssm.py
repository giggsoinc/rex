"""AWS Systems Manager Parameter Store provider.

Cheaper alternative to Secrets Manager. SecureString params support KMS encryption.
"""

from __future__ import annotations

import asyncio

import structlog

from rex.secrets.base import SecretNotFoundError, SecretProvider

logger = structlog.get_logger()


class AwsSsmParameterStoreProvider(SecretProvider):
    """AWS Systems Manager Parameter Store.

    Param naming: /rex/prod/gemini/api_key  (one param per field)
    Type: SecureString (KMS-encrypted) — automatically decrypted on fetch.

    Access via dotted key: "gemini.api_key" -> "/rex/prod/gemini/api_key"
    """

    def __init__(
        self,
        prefix: str = "/rex/prod/",
        region: str = "us-east-1",
    ) -> None:
        super().__init__()
        self.prefix = prefix.rstrip("/") + "/"
        self.region = region
        self._client = None

    def _get_client(self):
        """Lazy init boto3 SSM client."""
        if self._client is None:
            import boto3
            self._client = boto3.client("ssm", region_name=self.region)
        return self._client

    async def _fetch(self, key: str) -> str:
        param_path = f"{self.prefix}{key.replace('.', '/')}"

        def _do_fetch():
            client = self._get_client()
            try:
                response = client.get_parameter(Name=param_path, WithDecryption=True)
                return response["Parameter"]["Value"]
            except client.exceptions.ParameterNotFound:
                raise SecretNotFoundError(f"Parameter {param_path} not found")

        try:
            return await asyncio.to_thread(_do_fetch)
        except SecretNotFoundError:
            raise
        except Exception as e:
            logger.error("aws_ssm_fetch_failed", param=param_path, error=str(e))
            raise SecretNotFoundError(f"Failed to fetch {param_path}: {e}") from e

    async def health_check(self) -> bool:
        """List params with our prefix — verify auth + reachability."""
        def _do_check():
            client = self._get_client()
            client.describe_parameters(MaxResults=1, ParameterFilters=[
                {"Key": "Name", "Option": "BeginsWith", "Values": [self.prefix]}
            ])
            return True

        try:
            return await asyncio.to_thread(_do_check)
        except Exception as e:
            logger.error("aws_ssm_health_failed", error=str(e))
            return False
