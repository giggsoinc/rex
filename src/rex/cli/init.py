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
from rich.prompt import Confirm

from rex.cli.init_io import banner, summary, verify_vector_store, write_env
from rex.cli.init_llm import ask_llm_config
from rex.cli.init_secrets import ask_secret_provider
from rex.cli.init_steps import (
    ask_chroma_config,
    ask_deployment_mode,
    ask_local_lancedb_config,
    ask_oracle_config,
    ask_pgvector_config,
    ask_shared_lancedb_config,
    ask_storage_path,
    ask_vector_store,
    ask_vision_config,
)

console = Console()

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_LOCAL = REPO_ROOT / ".env.local"
ENV_ENTERPRISE = REPO_ROOT / ".env.enterprise"


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
