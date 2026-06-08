"""Classification + dedup logic mixin for LLMRouter.

Extracted from router.py to keep modules under the line limit. The mixin
expects the host class to provide: self.model, self.settings, self.MAX_RETRIES,
self.project_context, self.taxonomy_hints, self.tag_vocabulary.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from pydantic import ValidationError

from rex.agents.router_prompt import SYSTEM_PROMPT, build_user_prompt, extract_json
from rex.models.schemas import DedupStatus, FileAction, FileContext, FileDecision

logger = structlog.get_logger()


class RouterLogicMixin:
    """Holds the LLM call/retry and decision building logic."""

    async def _classify_with_retry(self, context: FileContext) -> FileDecision:
        """Call the LLM; retry on JSON / validation failure."""
        prompt = build_user_prompt(context)
        system = self._build_system_prompt()
        last_error: Exception | None = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                raw = await self.model.generate(prompt, system=system, json_mode=True)
                data = extract_json(raw)
                return self._build_decision(data, context)
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                last_error = e
                logger.warning(
                    "router_parse_failed",
                    attempt=attempt,
                    file=context.file_record.filename,
                    error=str(e)[:200],
                )
                # Back off
                await asyncio.sleep(0.5 * attempt)
            except Exception as e:
                last_error = e
                logger.warning(
                    "router_llm_failed",
                    attempt=attempt,
                    file=context.file_record.filename,
                    error=str(e)[:200],
                )
                await asyncio.sleep(0.5 * attempt)

        # All retries failed — fallback decision
        logger.error(
            "router_all_retries_failed",
            file=context.file_record.filename,
            error=str(last_error)[:200] if last_error else "unknown",
        )
        return self._fallback_decision(context)

    def _build_system_prompt(self) -> str:
        """Compose system prompt — base + per-project context if set."""
        parts = [SYSTEM_PROMPT]
        if self.project_context:
            parts.append("")
            parts.append("PROJECT CONTEXT:")
            parts.append(self.project_context.strip())
        if self.taxonomy_hints:
            parts.append("")
            parts.append("SUGGESTED CATEGORY VOCABULARY:")
            for h in self.taxonomy_hints:
                parts.append(f"  - {h}")
        if self.tag_vocabulary:
            parts.append("")
            parts.append("SUGGESTED TAG VOCABULARY (prefer these tags when applicable):")
            parts.append("  " + ", ".join(self.tag_vocabulary))
        return "\n".join(parts)

    def _build_decision(self, data: dict[str, Any], context: FileContext) -> FileDecision:
        """Validate + normalize raw LLM output into a FileDecision."""
        # Normalize fields with safe defaults
        category = (data.get("category") or self._infer_default_category(context)).strip()
        category = category.strip("/").replace("\\", "/")
        tags_raw = data.get("tags", []) or []
        if isinstance(tags_raw, str):
            tags_raw = [tags_raw]
        tags = [str(t).strip().lower().replace(" ", "-") for t in tags_raw if t][:5]
        relevance = int(data.get("relevance", 3))
        relevance = max(1, min(5, relevance))
        action_raw = str(data.get("action", "keep")).strip().lower()
        if action_raw not in {"keep", "archive", "trash"}:
            action_raw = "keep"
        reasoning = str(data.get("reasoning", "Classified by Rex router")).strip()[:500]
        # Confidence — LLM self-reported; clamp to [0, 1]. Default 0.5 if missing
        # so legacy LLMs that ignore the new field don't silently route everything
        # to auto-place. 0.5 will trip the default 0.7 threshold → _Review/.
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        return FileDecision(
            category=category,
            tags=tags,
            relevance=relevance,
            action=FileAction(action_raw),
            reasoning=reasoning,
            confidence=confidence,
            duplicate_of=None,
            dedup_status=DedupStatus.UNIQUE,
        )

    def _fallback_decision(self, context: FileContext) -> FileDecision:
        """When LLM fails entirely — assign a default category by media type."""
        rec = context.file_record
        category = self._infer_default_category(context)
        return FileDecision(
            category=category,
            tags=["unclassified"],
            relevance=3,
            action=FileAction.KEEP,
            reasoning="LLM router unavailable; default classification by media type.",
        )
