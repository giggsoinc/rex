"""Version supersession detector — finds V<N> markers in filenames.

Use case: a folder contains
    20191021_SOW_CH_GG_V2_sow.docx
    20191024_SOW_CH_GG_V3_sow.docx
Both have different sha256 (V3 has new content) so they pass dedup. But
intent-wise V3 supersedes V2 and V2 should be archived as stale, not kept
in the main domain folder.

Algorithm:
  1. For each filename, strip the V<N> token (case-insensitive) to get a stem
  2. Group records by (stem, extension)
  3. For each group with >1 file, the highest V<N> is canonical; others are
     marked SUPERSEDED with `superseded_by` pointing at the canonical file_id
  4. Files with no V<N> marker are skipped (always treated as unique)

Returns a dict: {file_id: SupersessionInfo} for every stale file.
The SortEngine consumes this map and routes flagged files to _Stale/.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

import structlog

from rex.models.schemas import FileRecord

logger = structlog.get_logger()

__all__ = ["SupersessionInfo", "detect_versions", "strip_version"]

# Matches _V2, -V2, V10, _v3, etc. Bounded by _ - . or string end (not \b
# because underscore is a word character so \b would never fire here).
_VERSION_RE = re.compile(r"[_\-][vV](\d+)(?=[_\-.]|$)", re.IGNORECASE)

# YYYYMMDD_ prefix (Giggso convention) — stripped so V2 vs V3 on different days group together
_DATE_PREFIX_RE = re.compile(r"^\d{8}_")


@dataclass
class SupersessionInfo:
    """Record explaining why a file is marked stale."""

    file_id: str
    superseded_by: str   # file_id of the canonical (highest-V) file
    own_version: int     # this file's V<N>
    canonical_version: int  # the winning V<N>
    group_stem: str      # the normalized stem these files share


def strip_version(filename: str) -> tuple[str, int | None]:
    """Return (stem_without_V_marker_or_date, version_int_or_None).

    Also strips a leading YYYYMMDD_ prefix so V2 vs V3 from different days
    group together as one document with two versions.

    Examples:
      strip_version("foo_V2_sow.docx")               → ("foo_sow.docx", 2)
      strip_version("20191021_SOW_GG_V2_sow.docx")   → ("SOW_GG_sow.docx", 2)
      strip_version("foo_sow.docx")                  → ("foo_sow.docx", None)
    """
    match = _VERSION_RE.search(filename)
    if not match:
        return filename, None
    version = int(match.group(1))
    stripped = _VERSION_RE.sub("", filename, count=1)
    stripped = _DATE_PREFIX_RE.sub("", stripped)
    # Collapse double underscores left behind by the strip
    stripped = re.sub(r"[_\-]{2,}", "_", stripped).strip("_-")
    return stripped, version


def detect_versions(
    records: list[FileRecord],
) -> dict[str, SupersessionInfo]:
    """Identify stale files (older V<N> in a version group). Returns
    {file_id: SupersessionInfo} for files that should be marked SUPERSEDED.

    Files without a V<N> marker are not analyzed (always treated as unique).
    Groups with only one V<N> file are also skipped (nothing to supersede).
    """
    # Group: (stem, extension) -> list[(version_int, file_id, original_filename)]
    groups: dict[tuple[str, str], list[tuple[int, str, str]]] = defaultdict(list)
    for rec in records:
        stem, version = strip_version(rec.filename)
        if version is None:
            continue
        key = (stem.lower(), rec.extension.lower())
        groups[key].append((version, rec.id, rec.filename))

    superseded: dict[str, SupersessionInfo] = {}
    for (stem, _ext), members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda t: t[0])  # ascending by version
        canonical_version, canonical_id, _ = members[-1]
        for v, file_id, filename in members[:-1]:
            superseded[file_id] = SupersessionInfo(
                file_id=file_id,
                superseded_by=canonical_id,
                own_version=v,
                canonical_version=canonical_version,
                group_stem=stem,
            )

    if superseded:
        logger.info(
            "version_supersession_detected",
            total_stale=len(superseded),
            groups_affected=sum(1 for m in groups.values() if len(m) > 1),
        )
    return superseded
