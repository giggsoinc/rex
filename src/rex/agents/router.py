"""LLM Router agent — classifies, tags, dedups, decides action.

Receives FileContext (file + embedding + neighbors + existing catalog).
Calls LLM with structured prompt → typed FileDecision.
Applies dedup logic on top of LLM output (deterministic where possible).
3-retry-with-backoff for LLM JSON parsing failures.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import structlog
from pydantic import ValidationError

from rex.config import Settings, get_settings
from rex.ml.provider import ModelProvider
from rex.models.schemas import (
    DedupStatus,
    FileAction,
    FileContext,
    FileDecision,
)

logger = structlog.get_logger()


SYSTEM_PROMPT = """You are Rex, an expert knowledge librarian.

You classify files into a clean folder structure for long-term knowledge management.

You MUST return ONLY valid JSON matching this exact schema:
{
  "category": "string — folder path like 'Documents/Finance' or 'Presentations/Q3'",
  "tags": ["array", "of", "descriptive", "tags"],
  "relevance": 1-5 integer,
  "action": "keep" | "archive" | "trash",
  "reasoning": "one sentence explanation"
}

Rules:
- relevance: 5 = critical, 4 = important, 3 = useful, 2 = marginal, 1 = junk
- action=trash only when relevance is 1 (clearly junk/temp/noise)
- action=archive for old or rarely-needed content (relevance 2-3)
- action=keep for current/useful content (relevance 3-5)
- Reuse existing categories where they fit; only invent new categories when needed
- Categories use forward slashes like "Documents/Contracts" — no leading slash
- Tags are lowercase, no spaces (use hyphens), 1-5 tags max
- Be deterministic — same file content = same classification
"""


def build_user_prompt(context: FileContext) -> str:
    """Construct the user prompt sent to the LLM."""
    rec = context.file_record
    text_preview = (rec.extracted_text or "")[:1500]
    image_desc = rec.image_description or ""
    neighbors = context.similar_files
    cats = context.existing_categories

    parts = [
        "Classify this file.",
        "",
        "FILE METADATA:",
        f"  filename: {rec.filename}",
        f"  extension: {rec.extension}",
        f"  media_type: {rec.media_type.value}",
        f"  size_bytes: {rec.size_bytes}",
        f"  modified_at: {rec.modified_at}",
    ]
    if text_preview.strip():
        parts.extend(["", "EXTRACTED TEXT (first 1500 chars):", text_preview])
    if image_desc:
        parts.extend(["", "IMAGE DESCRIPTION (from vision):", image_desc])
    if neighbors:
        parts.append("")
        parts.append("SIMILAR FILES (top by embedding):")
        for n in neighbors:
            parts.append(
                f"  - {n.filename} (similarity={n.similarity_score:.2f})"
            )
    if cats:
        parts.append("")
        parts.append("EXISTING CATEGORIES (reuse if appropriate):")
        for c in cats:
            parts.append(f"  - {c}")
    parts.extend(["", "Return JSON now."])
    return "\n".join(parts)


JSON_BLOCK_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def extract_json(raw: str) -> dict[str, Any]:
    """Pull the first plausible JSON object out of a model response.

    Models sometimes wrap JSON in markdown fences or add chatter; this is forgiving.
    """
    raw = raw.strip()
    # Strip markdown fences
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Try to find a JSON object in the text
    matches = JSON_BLOCK_RE.findall(raw)
    for m in matches:
        try:
            return json.loads(m)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"No valid JSON in model output: {raw[:300]}")


class LLMRouter:
    """LLM-driven file classification + deterministic dedup."""

    MAX_RETRIES = 3

    def __init__(
        self,
        model_provider: ModelProvider,
        settings: Settings | None = None,
    ) -> None:
        self.model = model_provider
        self.settings = settings or get_settings()
        # Project-level context (set by builder when scanning inside a project)
        self.project_context: str = ""
        self.taxonomy_hints: list[str] = []
        self.tag_vocabulary: list[str] = []

    async def route(self, context: FileContext) -> FileDecision:
        """Classify and decide. Applies dedup logic on top of LLM output."""
        # Step 1: dedup check FIRST — cheaper than LLM, deterministic
        dedup_result = self._check_dedup(context)

        # Step 2: LLM classification (we still classify even duplicates,
        # so they have a category for inspection)
        decision = await self._classify_with_retry(context)

        # Step 3: overlay dedup result
        if dedup_result is not None:
            decision.dedup_status = dedup_result.status
            decision.duplicate_of = dedup_result.duplicate_of
            # Duplicates auto-route to trash unless original is missing
            if dedup_result.status == DedupStatus.EXACT_DUPLICATE:
                decision.action = FileAction.TRASH
                if not decision.reasoning.lower().startswith("exact duplicate"):
                    decision.reasoning = f"Exact duplicate of {dedup_result.duplicate_of}; " + decision.reasoning
            elif dedup_result.status == DedupStatus.NEAR_DUPLICATE:
                decision.action = FileAction.ARCHIVE
                decision.reasoning = (
                    f"Near-duplicate of {dedup_result.duplicate_of} "
                    f"(similarity={dedup_result.similarity:.2f}); " + decision.reasoning
                )

        return decision

    # --- LLM call with retry ---

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

        return FileDecision(
            category=category,
            tags=tags,
            relevance=relevance,
            action=FileAction(action_raw),
            reasoning=reasoning,
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

    @staticmethod
    def _infer_default_category(context: FileContext) -> str:
        """Heuristic category if router can't decide."""
        rec = context.file_record
        ext = rec.extension.lower()
        if ext in {".pdf", ".doc", ".docx", ".odt", ".rtf"}:
            return "Documents"
        if ext in {".ppt", ".pptx", ".odp"}:
            return "Presentations"
        if ext in {".xls", ".xlsx", ".ods", ".csv"}:
            return "Spreadsheets"
        if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
            return "Images"
        if ext in {".mp4", ".mov", ".avi", ".mkv"}:
            return "Videos"
        if ext in {".mp3", ".wav", ".flac"}:
            return "Audio"
        if ext in {".md", ".txt", ".rst"}:
            return "Notes"
        if ext in {".py", ".js", ".ts", ".go", ".java"}:
            return "Code"
        if ext in {".zip", ".tar", ".gz", ".7z"}:
            return "Archives"
        return "Other"

    # --- Dedup ---

    def _check_dedup(self, context: FileContext) -> _DedupResult | None:
        """Examine neighbors for exact/near duplicates.

        Returns None if no dedup signal; else a _DedupResult.
        """
        near_threshold = self.settings.dedup_near_threshold
        related_threshold = self.settings.dedup_related_threshold

        for n in context.similar_files:
            if n.similarity_score >= 0.9999:
                # Treat ≥0.9999 as exact (same hash would yield 1.0)
                return _DedupResult(
                    status=DedupStatus.EXACT_DUPLICATE,
                    duplicate_of=n.file_id,
                    similarity=n.similarity_score,
                )
            if n.similarity_score >= near_threshold:
                return _DedupResult(
                    status=DedupStatus.NEAR_DUPLICATE,
                    duplicate_of=n.file_id,
                    similarity=n.similarity_score,
                )
            if n.similarity_score >= related_threshold:
                return _DedupResult(
                    status=DedupStatus.RELATED,
                    duplicate_of=n.file_id,
                    similarity=n.similarity_score,
                )
            break  # only check top neighbor for dedup classification
        return None


class _DedupResult:
    __slots__ = ("status", "duplicate_of", "similarity")

    def __init__(self, status: DedupStatus, duplicate_of: str, similarity: float) -> None:
        self.status = status
        self.duplicate_of = duplicate_of
        self.similarity = similarity
