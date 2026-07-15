"""Content artifact storage (P7A-8): render an approved draft to Markdown + PDF
under a controlled root the API can serve, mirroring ``audit_artifacts``.

The publish path uses this for the ``PDF/Markdown`` target AND as the DEGRADED
fallback when a WordPress publish has no per-site credential (artifact-only, never
a crash). Files land in ``<root>/<code>/`` and the returned relative keys drive the
job's ``pdf_path`` / ``md_path`` columns. :meth:`resolve` refuses any key that
escapes the root (the same path-traversal guard as ``LocalArtifactStore``), so a
crafted key can never read an arbitrary file.

The PDF is a small, dependency-free single-page document carrying the draft TITLE
(the full long-form body lives in the Markdown file next to it) - enough for a real,
downloadable artifact without pulling a heavy HTML->PDF renderer into the base
install. A later chunk can swap in a full renderer behind this same seam.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.config import Settings

_MD_NAME = "content.md"
_PDF_NAME = "content.pdf"


class ContentArtifactStore(Protocol):
    """Persist a rendered draft; return ``(pdf_key, md_key)`` (None if not written)."""

    def store(
        self, code: str, *, markdown: str | None, title: str
    ) -> tuple[str | None, str | None]: ...

    def resolve(self, key: str) -> Path | None: ...


class LocalContentArtifactStore:
    """Writes ``<root>/<code>/content.md`` + ``content.pdf`` on a shared filesystem."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def store(
        self, code: str, *, markdown: str | None, title: str
    ) -> tuple[str | None, str | None]:
        if markdown is None:
            return None, None
        dest_dir = self._root / code
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / _MD_NAME).write_text(markdown, encoding="utf-8")
        (dest_dir / _PDF_NAME).write_bytes(_minimal_pdf(title or code))
        return f"{code}/{_PDF_NAME}", f"{code}/{_MD_NAME}"

    def resolve(self, key: str) -> Path | None:
        """Resolve a stored key to a real file within the root, or ``None``.

        Refuses any key that escapes the root (``..`` / absolute), so a crafted
        key can never read an arbitrary file (mirrors ``LocalArtifactStore``).
        """
        if not key:
            return None
        root = self._root.resolve()
        target = (self._root / key).resolve()
        if not target.is_relative_to(root):
            return None
        return target if target.is_file() else None


def content_store_from_settings(settings: Settings) -> LocalContentArtifactStore | None:
    """Build the content artifact store, or ``None`` when no root is configured.

    Prefers ``content_artifact_dir``; falls back to the shared ``audit_artifact_dir``
    so a single-root deploy needs to set only one path.
    """
    root = settings.content_artifact_dir or settings.audit_artifact_dir
    return LocalContentArtifactStore(root) if root else None


# --------------------------------------------------------------------------- #
# A tiny, dependency-free PDF writer (single page, one line: the title).
# --------------------------------------------------------------------------- #
def _pdf_escape(text: str) -> str:
    """Escape a string for a PDF literal ``(...)`` object and bound its length."""
    cleaned = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in text)
    return cleaned.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")[:180]


def _minimal_pdf(title: str) -> bytes:
    """A valid one-page PDF showing ``title`` (the .md carries the full body).

    Assembles the five core objects + a byte-accurate xref table by hand, so no
    third-party dependency is needed. Latin-1 encodable by construction (see
    :func:`_pdf_escape`).
    """
    content = f"BT /F1 16 Tf 72 720 Td ({_pdf_escape(title)}) Tj ET".encode("latin-1")
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode("latin-1") + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("latin-1")
    return bytes(out)
