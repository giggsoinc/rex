"""Secret provider factory — returns the right backend based on config."""

from __future__ import annotations

from enum import Enum

import structlog

from rex.config import Settings, get_settings
from rex.secrets.base import SecretProvider

logger = structlog.get_logger()


class SecretBackend(str, Enum):
    """Supported secret backends."""

    FILE = "file"
    ENV = "env"
    AWS_SECRETS_MANAGER = "aws_secrets_manager"
    AWS_SSM = "aws_ssm"
    AZURE_KEYVAULT = "azure_keyvault"
    GCP_SECRET_MANAGER = "gcp_secret_manager"
    OCI_VAULT = "oci_vault"
    HASHICORP_VAULT = "vault"


_singleton: SecretProvider | None = None


def get_secret_provider(settings: Settings | None = None, *, fresh: bool = False) -> SecretProvider:
    """Construct (or return cached) SecretProvider based on REX_SECRET_PROVIDER.

    Args:
        settings: Override Settings; defaults to env-loaded.
        fresh: Bypass the singleton cache.

    Returns:
        Singleton SecretProvider instance.
    """
    global _singleton
    if _singleton is not None and not fresh:
        return _singleton

    s = settings or get_settings()
    backend = s.secret_provider

    logger.info("secret_provider_factory", backend=backend)

    if backend == SecretBackend.FILE.value:
        from rex.secrets.file_provider import FileSecretProvider
        _singleton = FileSecretProvider(path=s.secret_file_path)

    elif backend == SecretBackend.ENV.value:
        from rex.secrets.env_provider import EnvVarProvider
        _singleton = EnvVarProvider(prefix=s.secret_env_prefix)

    elif backend == SecretBackend.AWS_SECRETS_MANAGER.value:
        from rex.secrets.aws_secrets_manager import AwsSecretsManagerProvider
        _singleton = AwsSecretsManagerProvider(
            prefix=s.secret_prefix,
            region=s.secret_region,
        )

    elif backend == SecretBackend.AWS_SSM.value:
        from rex.secrets.aws_ssm import AwsSsmParameterStoreProvider
        _singleton = AwsSsmParameterStoreProvider(
            prefix=s.secret_prefix,
            region=s.secret_region,
        )

    elif backend == SecretBackend.AZURE_KEYVAULT.value:
        from rex.secrets.azure_keyvault import AzureKeyVaultProvider
        _singleton = AzureKeyVaultProvider(
            vault_url=s.secret_vault_url,
            prefix=s.secret_prefix,
        )

    elif backend == SecretBackend.GCP_SECRET_MANAGER.value:
        from rex.secrets.gcp_secret_manager import GcpSecretManagerProvider
        _singleton = GcpSecretManagerProvider(
            project_id=s.secret_project_id,
            prefix=s.secret_prefix,
        )

    elif backend == SecretBackend.OCI_VAULT.value:
        from rex.secrets.oci_vault import OciVaultProvider
        _singleton = OciVaultProvider(
            vault_id=s.secret_vault_id,
            compartment_id=s.secret_compartment_id,
            prefix=s.secret_prefix,
        )

    elif backend == SecretBackend.HASHICORP_VAULT.value:
        from rex.secrets.hashicorp_vault import HashiCorpVaultProvider
        _singleton = HashiCorpVaultProvider(
            vault_url=s.secret_vault_url,
            token=s.secret_vault_token or None,
            prefix=s.secret_prefix,
        )

    else:
        raise ValueError(f"Unsupported secret backend: {backend}")

    return _singleton


def reset_provider() -> None:
    """Reset the singleton — useful for tests."""
    global _singleton
    _singleton = None
