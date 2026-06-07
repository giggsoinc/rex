"""Prompt construction + JSON extraction for the LLM router.

Extracted from router.py to keep modules under the line limit.
"""

from __future__ import annotations

import json
import re
from typing import Any

from rex.models.schemas import FileContext


SYSTEM_PROMPT = """You are Rex, an expert knowledge librarian.

You classify files into a clean folder structure for long-term knowledge management.

You MUST return ONLY valid JSON matching this exact schema:
{
  "category": "string — folder path like 'Documents/Finance' or 'Presentations/Q3'",
  "tags": ["array", "of", "descriptive", "tags"],
  "relevance": 1-5 integer,
  "confidence": 0.0-1.0 float (REQUIRED — how sure are you?),
  "action": "keep" | "archive" | "trash",
  "reasoning": "one sentence explanation"
}

Rules:
- relevance: 5 = critical, 4 = important, 3 = useful, 2 = marginal, 1 = junk
- confidence: be honest. 0.9+ only when filename and content strongly agree;
  0.5-0.7 when you had to guess between two domains; <0.5 when truly uncertain.
  Low confidence triggers human review — do not inflate to avoid review.
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
