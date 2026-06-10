"""Rex — Multi-agent data cleanup and knowledge management system."""

import warnings as _warnings

# Suppress noisy-but-benign third-party warnings that pollute scan logs.
# These are output-correctness-irrelevant: LiteLLM's Pydantic serializer
# emits version-mismatch warnings on every LLM call; openpyxl complains
# about defined names that aren't print areas. Both are cosmetic.
_warnings.filterwarnings("ignore", message=r".*PydanticSerializationUnexpectedValue.*")
_warnings.filterwarnings("ignore", message=r".*Print area cannot be set.*")
_warnings.filterwarnings("ignore", message=r".*Workbook contains no default style.*")

__version__ = "0.1.0"
