"""Banner, summary, env writer, and vector-store verification for `rex init`."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def banner() -> None:
    """Print Rex onboarding banner."""
    console.print(
        Panel.fit(
            "[bold cyan]Rex[/bold cyan] — Data Cleanup & Knowledge Management\n"
            "[dim]Onboarding wizard — pick deployment mode and vector store[/dim]",
            border_style="cyan",
        )
    )


def write_env(config: dict, target_path: Path) -> None:
    """Write configuration to .env file."""
    lines = ["# Rex — Onboarding-generated config\n"]
    for key, value in config.items():
        # All-caps keys are raw env vars (LiteLLM API keys like OPENAI_API_KEY)
        env_key = key if key.isupper() else f"REX_{key.upper()}"
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
