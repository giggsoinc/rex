"""`rex init` — onboarding wizard. Picks deployment mode and vector store backend.

Generates .env.local (or .env.enterprise) and validates by health-checking the
chosen vector store.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_LOCAL = REPO_ROOT / ".env.local"
ENV_ENTERPRISE = REPO_ROOT / ".env.enterprise"


def banner() -> None:
    """Print Rex onboarding banner."""
    console.print(
        Panel.fit(
            "[bold cyan]Rex[/bold cyan] — Data Cleanup & Knowledge Management\n"
            "[dim]Onboarding wizard — pick deployment mode and vector store[/dim]",
            border_style="cyan",
        )
    )


def ask_deployment_mode() -> str:
    """Ask: local or enterprise?"""
    console.print("\n[bold]Step 1:[/bold] Deployment mode\n")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("[bold cyan]local[/bold cyan]", "Single user, zero infra — LanceDB on disk")
    table.add_row("[bold cyan]enterprise[/bold cyan]", "Managed DB — pgvector / Oracle 26AI / ChromaDB")
    console.print(table)
    return Prompt.ask("\nChoose mode", choices=["local", "enterprise"], default="local")


def ask_vector_store(mode: str) -> str:
    """Ask which vector backend to use."""
    if mode == "local":
        console.print("\n[green]Vector store: LanceDB (auto — embedded, no infra)[/green]")
        return "lancedb"

    console.print("\n[bold]Step 2:[/bold] Enterprise vector store\n")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("[bold cyan]pgvector[/bold cyan]", "PostgreSQL + pgvector extension (self-hosted or RDS)")
    table.add_row("[bold cyan]oracle26ai[/bold cyan]", "Oracle 26AI Vector Store (managed)")
    table.add_row("[bold cyan]chromadb[/bold cyan]", "ChromaDB server (self-hosted)")
    table.add_row("[bold cyan]lancedb[/bold cyan]", "LanceDB on shared storage (S3, NFS)")
    console.print(table)
    return Prompt.ask(
        "\nChoose vector store",
        choices=["pgvector", "oracle26ai", "chromadb", "lancedb"],
        default="pgvector",
    )


def ask_local_lancedb_config() -> dict:
    """Ask for LanceDB local config."""
    path = Prompt.ask(
        "Vector storage path",
        default="~/rex-data/vectors.lance",
    )
    return {"vector_path": path}


def ask_pgvector_config() -> dict:
    """Ask for pgvector connection details."""
    console.print("\n[bold]Step 3:[/bold] pgvector connection details\n")
    host = Prompt.ask("Host", default="localhost")
    port = Prompt.ask("Port", default="5432")
    db = Prompt.ask("Database name", default="rex")
    user = Prompt.ask("Username", default="rex")
    password = Prompt.ask("Password", password=True)
    return {
        "vector_db_url": f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}",
        "vector_host": host,
        "vector_port": int(port),
        "vector_db": db,
        "vector_user": user,
        "vector_password": password,
    }


def ask_oracle_config() -> dict:
    """Ask for Oracle 26AI connection details."""
    console.print("\n[bold]Step 3:[/bold] Oracle 26AI connection details\n")
    host = Prompt.ask("Host", default="localhost")
    port = Prompt.ask("Port", default="1521")
    service = Prompt.ask("Service name", default="REXPDB")
    user = Prompt.ask("Username", default="rex_app")
    password = Prompt.ask("Password", password=True)
    return {
        "vector_host": host,
        "vector_port": int(port),
        "vector_service": service,
        "vector_user": user,
        "vector_password": password,
    }


def ask_chroma_config() -> dict:
    """Ask for ChromaDB connection details."""
    console.print("\n[bold]Step 3:[/bold] ChromaDB connection details\n")
    host = Prompt.ask("Host", default="localhost")
    port = Prompt.ask("Port", default="8000")
    collection = Prompt.ask("Collection name", default="rex_vectors")
    return {
        "vector_host": host,
        "vector_port": int(port),
        "vector_collection": collection,
    }


def ask_shared_lancedb_config() -> dict:
    """Ask for shared LanceDB (enterprise) path."""
    console.print("\n[bold]Step 3:[/bold] Shared LanceDB location\n")
    path = Prompt.ask(
        "Path (local filesystem or s3://...)",
        default="s3://company-rex-vectors/",
    )
    return {"vector_path": path}


def ask_llm_config() -> dict:
    """Ask which LLM provider to use."""
    console.print("\n[bold]LLM Provider[/bold]\n")
    provider = Prompt.ask(
        "Which LLM for classification?",
        choices=["ollama", "gemini", "bedrock"],
        default="ollama",
    )

    if provider == "ollama":
        endpoint = Prompt.ask("Ollama endpoint", default="http://localhost:11434")
        model = Prompt.ask("Model", default="qwen3:8b")
        return {"llm_provider": "ollama", "llm_endpoint": endpoint, "llm_model": model}
    elif provider == "gemini":
        model = Prompt.ask("Gemini model", default="gemini-3.1-flash-lite")
        api_key = Prompt.ask("Gemini API key", password=True)
        return {"llm_provider": "gemini", "llm_model": model, "gemini_api_key": api_key}
    else:
        model = Prompt.ask("Bedrock model", default="anthropic.claude-haiku-4-5-20251001")
        return {"llm_provider": "bedrock", "llm_model": model}


def ask_vision_config() -> dict:
    """Ask vision configuration."""
    console.print("\n[bold]Vision (for images and PDF embedded images)[/bold]\n")
    enable = Confirm.ask("Enable vision (recommended for images)?", default=True)
    if not enable:
        return {"vision_provider": "none"}
    api_key = Prompt.ask("Gemini API key (for vision)", password=True, default="")
    return {"vision_provider": "gemini", "gemini_api_key": api_key}


def ask_storage_path() -> dict:
    """Ask where Rex should put organized output."""
    console.print("\n[bold]Output[/bold]\n")
    path = Prompt.ask("Organized output path", default="~/rex-data/output")
    return {"storage_backend": "local", "storage_path": path}


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


def write_env(config: dict, target_path: Path) -> None:
    """Write configuration to .env file."""
    lines = ["# Rex — Onboarding-generated config\n"]
    for key, value in config.items():
        env_key = f"REX_{key.upper()}"
        lines.append(f"{env_key}={value}")
    target_path.write_text("\n".join(lines) + "\n")


async def verify_vector_store(config: dict) -> bool:
    """Spin up the configured vector store and health-check it."""
    from rex.config import Settings
    from rex.vectorstore import get_vector_store

    # Build Settings from collected config
    settings = Settings(**{k: v for k, v in config.items()})

    try:
        store = get_vector_store(settings)
        await store.initialize()
        ok = await store.health_check()
        await store.close()
        return ok
    except Exception as e:
        console.print(f"[red]Health check failed:[/red] {e}")
        return False


def summary(config: dict) -> None:
    """Print summary table of choices."""
    console.print("\n[bold]Configuration Summary[/bold]\n")
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Setting")
    table.add_column("Value")
    for key, value in config.items():
        # Mask passwords and API keys
        display = value
        if "password" in key.lower() or "api_key" in key.lower():
            display = "***" if value else "(not set)"
        table.add_row(key, str(display))
    console.print(table)


def main() -> int:
    """Run the onboarding wizard."""
    banner()

    mode = ask_deployment_mode()
    backend = ask_vector_store(mode)

    config: dict = {
        "deployment_mode": mode,
        "vector_store": backend,
    }

    # Vector store config
    if backend == "lancedb" and mode == "local":
        config.update(ask_local_lancedb_config())
    elif backend == "lancedb" and mode == "enterprise":
        config.update(ask_shared_lancedb_config())
    elif backend == "pgvector":
        config.update(ask_pgvector_config())
    elif backend == "oracle26ai":
        config.update(ask_oracle_config())
    elif backend == "chromadb":
        config.update(ask_chroma_config())

    # LLM + Vision + Storage + Secrets
    config.update(ask_llm_config())
    config.update(ask_vision_config())
    config.update(ask_storage_path())
    config.update(ask_secret_provider(mode))

    # Show summary
    summary(config)

    if not Confirm.ask("\nLooks good — save and continue?", default=True):
        console.print("[yellow]Aborted.[/yellow]")
        return 1

    # Write env file
    target = ENV_LOCAL if mode == "local" else ENV_ENTERPRISE
    write_env(config, target)
    console.print(f"[green]✓[/green] Wrote {target.relative_to(REPO_ROOT)}")

    # Health check
    if Confirm.ask("\nRun health check on vector store?", default=True):
        console.print("\n[cyan]Verifying vector store...[/cyan]")
        ok = asyncio.run(verify_vector_store(config))
        if ok:
            console.print("[green]✓ Vector store is healthy[/green]")
        else:
            console.print("[red]✗ Vector store check failed — review config[/red]")
            return 2

    console.print(
        Panel.fit(
            "[bold green]✓ Rex initialized[/bold green]\n\n"
            f"[dim]Config:[/dim] {target.name}\n"
            f"[dim]Mode:[/dim] {mode}\n"
            f"[dim]Vector store:[/dim] {backend}\n\n"
            "[bold]Next:[/bold] [cyan]rex scan <folder>[/cyan]",
            border_style="green",
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
