"""Rex — Multi-agent data cleanup and knowledge management system."""

import warnings as _warnings

# Suppress noisy-but-benign third-party warnings that pollute scan logs.
# These are output-correctness-irrelevant: LiteLLM's Pydantic serializer
# emits version-mismatch warnings on every LLM call; openpyxl complains
# about defined names that aren't print areas. Both are cosmetic.
_warnings.filterwarnings("ignore", message=r".*PydanticSerializationUnexpectedValue.*")
_warnings.filterwarnings("ignore", message=r".*Print area cannot be set.*")
_warnings.filterwarnings("ignore", message=r".*Workbook contains no default style.*")


def _route_logs_to_stderr() -> None:
    """Route ALL structlog output to stderr — stdout must stay clean.

    structlog's default PrintLogger writes to stdout. When Rex runs as an
    MCP stdio server, stdout is the JSON-RPC protocol stream — a single log
    line like '2026-06-10 ... [info] ...' corrupts it (the client parses
    '2026' as JSON then dies on the '-': "Unexpected non-whitespace
    character after JSON at position 4").

    Logs-to-stderr is the correct convention for every entry point (CLI,
    Streamlit, MCP), so configure it once here at package import.
    """
    import sys

    import structlog

    structlog.configure(
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


_route_logs_to_stderr()

__version__ = "0.1.0"
