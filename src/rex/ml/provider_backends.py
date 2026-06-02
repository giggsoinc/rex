"""Bedrock backend stubs — mixin for ModelProvider.

Split out of provider.py to satisfy the 150-line file limit. Stubs for cloud
deployment; set REX_LLM_PROVIDER=ollama for local use.
"""

from __future__ import annotations


class BedrockBackendMixin:
    """AWS Bedrock generate/embed stubs (cloud phase)."""

    async def _bedrock_generate(self, prompt: str, system: str, json_mode: bool) -> str:
        """Generate via AWS Bedrock. Stub for cloud deployment."""
        raise NotImplementedError(
            "Bedrock provider not yet implemented. Set REX_LLM_PROVIDER=ollama for local use."
        )

    async def _bedrock_embed(self, text: str) -> list[float]:
        """Embed via AWS Bedrock Titan. Stub for cloud deployment."""
        raise NotImplementedError(
            "Bedrock embedding not yet implemented. Set REX_LLM_PROVIDER=ollama for local use."
        )
