"""Interactive prompt steps for `rex init` — deployment, vector store, LLM, etc."""

from __future__ import annotations

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()


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


# ask_llm_config moved to init_llm.py — now offers every LiteLLM provider.


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
