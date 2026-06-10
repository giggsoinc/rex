"""Model provider — abstracts Ollama / Bedrock / OpenAI behind one interface.

The LLM Router calls provider.classify() and provider.embed().
The underlying model is swapped via REX_LLM_PROVIDER env var.
Same prompt, same Pydantic output, different backend.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import ollama
import structlog

from rex.config import LLMProvider, Settings, get_settings
from rex.ml.provider_backends import BedrockBackendMixin

logger = structlog.get_logger()


class ModelProvider(BedrockBackendMixin):
    """Unified interface to LLM and embedding models."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._ollama_client: ollama.AsyncClient | None = None

    @property
    def ollama(self) -> ollama.AsyncClient:
        """Lazy Ollama async client."""
        if self._ollama_client is None:
            self._ollama_client = ollama.AsyncClient(host=self.settings.llm_endpoint)
        return self._ollama_client

    async def generate(self, prompt: str, system: str = "", json_mode: bool = True) -> str:
        """Generate text — routes through LiteLLM task router (task='classify').

        Existing callers see no API change. Behind the scenes, this now goes
        through rex.ml.routing.get_router() which picks the model + fallback
        chain based on .raven/llm_routing.yaml (default: ollama/qwen3:8b →
        gemini/flash-lite). Cost logged to .raven/usage.jsonl per call.

        Falls back to the legacy direct-Ollama path if routing fails (e.g.
        LiteLLM not installed) so existing scans never break.
        """
        try:
            from rex.ml.routing import get_router
            return await get_router().chat(
                task="classify", prompt=prompt, system=system, json_mode=json_mode,
            )
        except Exception as e:
            logger.warning("routing_generate_fell_back_to_legacy", error=str(e)[:160])
            provider = self.settings.llm_provider
            if provider == LLMProvider.OLLAMA:
                return await self._ollama_generate(prompt, system, json_mode)
            if provider == LLMProvider.BEDROCK:
                return await self._bedrock_generate(prompt, system, json_mode)
            raise ValueError(f"Unsupported LLM provider: {provider}")

    async def embed(self, text: str) -> list[float]:
        """Embed text — routes through LiteLLM task router (task='embed').

        Default chain: ollama/all-minilm (local) with no cloud fallback (free).
        Falls back to direct Ollama if routing fails so scans never break.
        """
        try:
            from rex.ml.routing import get_router
            return await get_router().embed(task="embed", text=text)
        except Exception as e:
            logger.warning("routing_embed_fell_back_to_legacy", error=str(e)[:160])
            return await self._ollama_embed(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embed multiple texts concurrently.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.
        """
        semaphore = asyncio.Semaphore(self.settings.ollama_parallel)

        async def _embed_one(text: str) -> list[float]:
            async with semaphore:
                return await self.embed(text)

        return await asyncio.gather(*[_embed_one(t) for t in texts])

    # --- Ollama backend ---

    async def _ollama_generate(self, prompt: str, system: str, json_mode: bool) -> str:
        """Generate via local Ollama."""
        options: dict[str, Any] = {"temperature": 0}
        response = await self.ollama.chat(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            format="json" if json_mode else "",
            options=options,
        )
        return response["message"]["content"]

    async def _ollama_embed(self, text: str) -> list[float]:
        """Embed via local Ollama."""
        response = await self.ollama.embed(
            model=self.settings.embed_model,
            input=text,
        )
        return response["embeddings"][0]

    async def health_check(self) -> dict[str, bool]:
        """Check if model provider is reachable and models are available."""
        result: dict[str, bool] = {"llm": False, "embed": False}

        try:
            if self.settings.llm_provider == LLMProvider.OLLAMA:
                models_response = await self.ollama.list()
                available = [m["name"] for m in models_response.get("models", [])]
                result["llm"] = self.settings.llm_model in available or any(
                    self.settings.llm_model.split(":")[0] in m for m in available
                )
                result["embed"] = self.settings.embed_model in available or any(
                    self.settings.embed_model.split(":")[0] in m for m in available
                )
        except Exception as e:
            logger.error("model_provider_health_check_failed", error=str(e))

        return result

    async def warmup(self) -> None:
        """Pre-load models into memory to avoid cold-start latency."""
        logger.info("warming_up_models", llm=self.settings.llm_model, embed=self.settings.embed_model)
        try:
            # Trigger model load with a minimal request
            await self.embed("warmup")
            await self.generate("Respond with: {}", system="You are a test.", json_mode=True)
            logger.info("models_warmed_up")
        except Exception as e:
            logger.warning("model_warmup_failed", error=str(e))
