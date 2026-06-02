"""Secret-provider prompt step for `rex init`."""

from __future__ import annotations

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

console = Console()


def ask_secret_provider(mode: str) -> dict:
    """Ask which secret backend to use."""
    console.print("\n[bold]Secret Provider[/bold] (where API keys live)\n")

    if mode == "local":
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_row("[bold cyan]file[/bold cyan]", ".raven/manifest.secrets.json (recommended for local)")
        table.add_row("[bold cyan]env[/bold cyan]", "Environment variables (REX_GEMINI_API_KEY etc.)")
        console.print(table)
        choice = Prompt.ask("Secret backend", choices=["file", "env"], default="file")
    else:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_row("[bold cyan]aws_secrets_manager[/bold cyan]", "AWS Secrets Manager")
        table.add_row("[bold cyan]aws_ssm[/bold cyan]", "AWS Systems Manager Parameter Store")
        table.add_row("[bold cyan]azure_keyvault[/bold cyan]", "Azure Key Vault")
        table.add_row("[bold cyan]gcp_secret_manager[/bold cyan]", "GCP Secret Manager")
        table.add_row("[bold cyan]oci_vault[/bold cyan]", "Oracle OCI Vault")
        table.add_row("[bold cyan]vault[/bold cyan]", "HashiCorp Vault")
        table.add_row("[bold cyan]env[/bold cyan]", "Kubernetes-mounted env vars")
        table.add_row("[bold cyan]file[/bold cyan]", "Local file (NOT recommended for production)")
        console.print(table)
        choice = Prompt.ask(
            "Secret backend",
            choices=[
                "aws_secrets_manager", "aws_ssm",
                "azure_keyvault", "gcp_secret_manager",
                "oci_vault", "vault", "env", "file",
            ],
            default="aws_secrets_manager",
        )

    config: dict = {"secret_provider": choice}

    if choice == "file":
        config["secret_file_path"] = Prompt.ask("Secrets file path", default=".raven/manifest.secrets.json")
    elif choice == "env":
        config["secret_env_prefix"] = Prompt.ask("Env var prefix", default="REX_")
    elif choice in {"aws_secrets_manager", "aws_ssm"}:
        config["secret_prefix"] = Prompt.ask("Secret prefix", default="/rex/prod/")
        config["secret_region"] = Prompt.ask("AWS region", default="us-east-1")
    elif choice == "azure_keyvault":
        config["secret_vault_url"] = Prompt.ask("Vault URL (https://<vault>.vault.azure.net/)")
        config["secret_prefix"] = Prompt.ask("Secret name prefix", default="rex-prod-")
    elif choice == "gcp_secret_manager":
        config["secret_project_id"] = Prompt.ask("GCP project ID")
        config["secret_prefix"] = Prompt.ask("Secret name prefix", default="rex-prod-")
    elif choice == "oci_vault":
        config["secret_vault_id"] = Prompt.ask("OCI Vault OCID")
        config["secret_compartment_id"] = Prompt.ask("Compartment OCID")
        config["secret_prefix"] = Prompt.ask("Secret name prefix", default="rex_prod_")
    elif choice == "vault":
        config["secret_vault_url"] = Prompt.ask("Vault URL", default="http://localhost:8200")
        token = Prompt.ask("Vault token (leave empty for K8s/AppRole auth)", password=True, default="")
        if token:
            config["secret_vault_token"] = token
        config["secret_prefix"] = Prompt.ask("KV path prefix", default="rex/prod/")

    return config
