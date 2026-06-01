"""Rex secret provider — abstracts where API keys/credentials come from.

Dev:     file (.raven/manifest.secrets.json)
Cloud:   AWS Secrets Manager / Parameter Store, Azure Key Vault,
         GCP Secret Manager, OCI Vault, HashiCorp Vault
K8s:     environment variables mounted from k8s Secrets

All Rex code uses get_secret_provider(settings).get("gemini.api_key").
Backend swaps via REX_SECRET_PROVIDER env var.
"""

from rex.secrets.base import SecretNotFoundError, SecretProvider
from rex.secrets.factory import get_secret_provider

__all__ = ["SecretProvider", "SecretNotFoundError", "get_secret_provider"]
