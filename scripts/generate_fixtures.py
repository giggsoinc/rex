"""Generate test fixtures for Rex overnight build.

Creates a realistic messy folder with 14 mixed files including duplicates,
near-duplicates, and varied content types — exactly what Rex would be pointed at.
"""

from __future__ import annotations

import shutil
import struct
import zlib
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample-data"


def make_text_file(path: Path, content: str) -> None:
    """Write a UTF-8 text file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_minimal_pdf(path: Path, body_text: str) -> None:
    """Write a minimal valid PDF — text content extractable by Unstructured."""
    # Minimal single-page PDF with one text stream. Hand-crafted spec-compliant bytes.
    content = f"BT /F1 12 Tf 72 720 Td ({body_text}) Tj ET"
    content_bytes = content.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content_bytes)} >>\nstream\n".encode("latin-1") + content_bytes + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    parts = [b"%PDF-1.4\n"]
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(sum(len(p) for p in parts))
        parts.append(f"{i} 0 obj\n".encode("latin-1") + obj + b"\nendobj\n")

    xref_offset = sum(len(p) for p in parts)
    xref = [f"xref\n0 {len(objects) + 1}\n".encode("latin-1"), b"0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n".encode("latin-1"))
    parts.extend(xref)
    parts.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("latin-1")
    )
    parts.append(f"startxref\n{xref_offset}\n%%EOF".encode("latin-1"))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(parts))


def make_minimal_png(path: Path, width: int = 8, height: int = 8, color: tuple = (255, 0, 0)) -> None:
    """Write a minimal valid PNG — solid color square."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    raw = b"".join(b"\x00" + bytes(color) * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    path.write_bytes(png)


def main() -> None:
    """Generate the test fixture set."""
    if FIXTURES.exists():
        shutil.rmtree(FIXTURES)
    FIXTURES.mkdir(parents=True)

    # --- Text/Markdown files (4) ---
    make_text_file(
        FIXTURES / "meeting_notes_2024_q3.md",
        "# Q3 Planning Meeting\n\nDate: 2024-09-15\nAttendees: Alice, Bob, Carol\n\n"
        "## Action items\n- Finalize budget by Oct 1\n- Hire 2 engineers\n- Q4 OKRs draft\n",
    )
    make_text_file(
        FIXTURES / "project_readme.md",
        "# Project Atlas\n\nInternal data platform.\n\n## Stack\n- Python\n- PostgreSQL\n- React\n",
    )
    make_text_file(
        FIXTURES / "random_note.txt",
        "Don't forget to call mom on Sunday. Pick up groceries. Renew car insurance.",
    )
    make_text_file(
        FIXTURES / "todo.txt",
        "1. Finish Rex MVP\n2. Test pipeline\n3. Document everything\n4. Demo to team\n",
    )

    # --- PDFs (3) ---
    make_minimal_pdf(
        FIXTURES / "quarterly_report_Q3_2024.pdf",
        "Q3 2024 Revenue Report. Total revenue grew 23 percent. Engineering hires on track."
    )
    make_minimal_pdf(
        FIXTURES / "engineering_handbook.pdf",
        "Engineering Handbook. Code review process. Deployment checklist. On-call rotation."
    )
    make_minimal_pdf(
        FIXTURES / "contract_acme_corp.pdf",
        "Master Services Agreement between Atlas Inc and Acme Corp. Term: 24 months."
    )

    # --- Images (2 + 1 duplicate) ---
    make_minimal_png(FIXTURES / "diagram_architecture.png", 16, 16, (0, 100, 200))
    make_minimal_png(FIXTURES / "team_photo.png", 16, 16, (200, 100, 50))

    # --- Duplicates ---
    # Exact duplicate of meeting_notes (same hash)
    shutil.copy(FIXTURES / "meeting_notes_2024_q3.md", FIXTURES / "meeting_notes_2024_q3_COPY.md")

    # Near-duplicate: same content, different filename, tiny edit at end
    make_text_file(
        FIXTURES / "meeting_notes_2024_q3_v2.md",
        "# Q3 Planning Meeting\n\nDate: 2024-09-15\nAttendees: Alice, Bob, Carol\n\n"
        "## Action items\n- Finalize budget by Oct 1\n- Hire 2 engineers\n- Q4 OKRs draft\n\nUpdated: 2024-09-20.\n",
    )

    # --- Junk files (2) ---
    make_text_file(FIXTURES / "old_temp_file.txt", "asdf asdf 1234 random nonsense gibberish")
    make_text_file(FIXTURES / "log_extract.txt", "[INFO] 2023-01-01 line 1\n[ERROR] line 2\n[INFO] line 3\n")

    # --- Nested folder ---
    make_text_file(
        FIXTURES / "subfolder" / "nested_doc.md",
        "# Nested Document\n\nThis lives in a subfolder. Should be discovered by recursive walk.",
    )

    files = sorted(FIXTURES.rglob("*"))
    real_files = [f for f in files if f.is_file()]
    print(f"Generated {len(real_files)} fixture files at {FIXTURES}")
    for f in real_files:
        print(f"  {f.relative_to(FIXTURES)} ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
