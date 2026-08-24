"""Content artifact storage (P7A-8): render an approved draft to Markdown + PDF
under a controlled root the API can serve, mirroring ``audit_artifacts``.

The publish path uses this for the ``PDF/Markdown`` target AND as the DEGRADED
fallback when a WordPress publish has no per-site credential (artifact-only, never
a crash). Files land in ``<root>/<code>/`` and the returned relative keys drive the
job's ``pdf_path`` / ``md_path`` columns. :meth:`resolve` refuses any key that
escapes the root (the same path-traversal guard as ``LocalArtifactStore``), so a
crafted key can never read an arbitrary file.

The PDF is a dependency-free, PAGINATED rendering of the draft: title, headings,
wrapped body prose, and bullet lists, across as many pages as the body needs.

It used to be a single page carrying ONLY the title, while `_emit_content_deliverable`
PREFERRED the PDF over the Markdown - so the client downloaded a near-blank page and
the actual article was never handed over. The "a later chunk can swap in a full
renderer" note that used to sit here is why that survived: it read as a deliberate
staging decision rather than a broken deliverable.

Deliberately NOT supported: embedded raster images. Writing JPEG XObjects by hand
(/DCTDecode streams, per-image resource dictionaries) is real work for a record
artifact whose images are already live on the published page, so an image renders as
a captioned reference line, not a silent omission. The base install stays free of
weasyprint / reportlab / Pillow.
"""

from __future__ import annotations

import re
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
        (dest_dir / _PDF_NAME).write_bytes(render_pdf(markdown, title=title or code))
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
# A dependency-free, paginating PDF writer.
# --------------------------------------------------------------------------- #
# Page geometry, in PDF points (1/72").
_PAGE_W, _PAGE_H = 612.0, 792.0
_MARGIN = 72.0
_TEXT_W = _PAGE_W - 2 * _MARGIN

# Helvetica's average advance is ~0.5em across mixed-case prose. Estimating rather
# than embedding the AFM width table keeps this stdlib-only; the cost is that a line
# of unusually wide glyphs wraps slightly early, which is invisible in prose.
_AVG_CHAR_EM = 0.5

# (font, size, leading, space_before) per block kind.
_STYLES: dict[str, tuple[str, float, float, float]] = {
    "title": ("F2", 19.0, 24.0, 0.0),
    "h1":    ("F2", 16.0, 21.0, 14.0),
    "h2":    ("F2", 13.5, 18.0, 12.0),
    "h3":    ("F2", 11.5, 16.0, 10.0),
    "body":  ("F1", 10.5, 15.0, 7.0),
    "bullet": ("F1", 10.5, 15.0, 3.0),
    "note":  ("F1", 9.0, 13.0, 7.0),
}

_INLINE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_INLINE_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_INLINE_EMPH = re.compile(r"(\*\*|__|\*|_|`)")


def _pdf_escape(text: str) -> str:
    """Escape a string for a PDF literal ``(...)`` object.

    Non-Latin-1 characters are transliterated to ASCII punctuation where there is an
    obvious equivalent and dropped otherwise, so the writer is total: no input can
    raise a UnicodeEncodeError mid-publish.
    """
    swaps = {
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "-", "\u2026": "...", "\u00a0": " ",
    }
    cleaned = "".join(swaps.get(ch, ch) for ch in text)
    cleaned = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in cleaned)
    return cleaned.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _strip_inline(text: str) -> str:
    """Flatten inline markdown to plain prose, keeping link targets visible.

    A link becomes ``text (url)`` rather than bare ``text``: the PDF is a record
    artifact, so a reader who cannot click needs the destination on the page.
    """
    text = _INLINE_IMG.sub(lambda m: f"[image: {m.group(1) or 'untitled'} - {m.group(2)}]", text)
    text = _INLINE_LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    return _INLINE_EMPH.sub("", text).strip()


def _wrap(text: str, *, size: float, indent: float = 0.0) -> list[str]:
    """Greedy word-wrap to the text column. Never drops a word: an over-long token
    (a URL) occupies its own line rather than being silently truncated."""
    limit = max(8, int((_TEXT_W - indent) / (size * _AVG_CHAR_EM)))
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines or [""]


def _blocks(markdown: str, *, title: str) -> list[tuple[str, str]]:
    """Parse markdown into ``(kind, text)`` blocks. Unknown syntax degrades to body
    prose - a rendering path must never lose the client's words."""
    out: list[tuple[str, str]] = [("title", title)]
    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            continue
        if stripped.startswith("### "):
            out.append(("h3", _strip_inline(stripped[4:])))
        elif stripped.startswith("## "):
            out.append(("h2", _strip_inline(stripped[3:])))
        elif stripped.startswith("# "):
            head = _strip_inline(stripped[2:])
            # The H1 duplicates the title page heading; keep one.
            if head.lower() != title.strip().lower():
                out.append(("h1", head))
        elif stripped.startswith(("- ", "* ", "+ ")):
            out.append(("bullet", _strip_inline(stripped[2:])))
        elif _INLINE_IMG.fullmatch(stripped):
            out.append(("note", _strip_inline(stripped)))
        else:
            out.append(("body", _strip_inline(stripped)))
    return [(k, t) for k, t in out if t]


def render_pdf(markdown: str | None, *, title: str) -> bytes:
    """Render ``markdown`` to a paginated, dependency-free PDF.

    Always returns a valid PDF: an empty or None body yields a title page rather than
    raising, because this sits on the publish path and a deliverable that fails to
    render must never fail the publish.
    """
    lines: list[tuple[str, str, float, float]] = []  # (font, text, size, advance)
    for kind, text in _blocks(markdown or "", title=title):
        font, size, leading, space_before = _STYLES[kind]
        indent = 14.0 if kind == "bullet" else 0.0
        wrapped = _wrap(text, size=size, indent=indent)
        for i, ln in enumerate(wrapped):
            body = f"- {ln}" if (kind == "bullet" and i == 0) else ln
            advance = leading + (space_before if i == 0 else 0.0)
            lines.append((font, body, size, advance))

    # Paginate.
    usable = _PAGE_H - 2 * _MARGIN
    pages: list[list[tuple[str, str, float, float]]] = []
    current: list[tuple[str, str, float, float]] = []
    used = 0.0
    for item in lines:
        if used + item[3] > usable and current:
            pages.append(current)
            current, used = [], 0.0
        current.append(item)
        used += item[3]
    pages.append(current)

    streams: list[bytes] = []
    for page in pages:
        parts = [b"BT"]
        y = _PAGE_H - _MARGIN
        for font, text, size, advance in page:
            y -= advance
            indent = _MARGIN + (14.0 if text.startswith("- ") else 0.0)
            parts.append(
                f"1 0 0 1 {indent:.1f} {y:.1f} Tm /{font} {size:.1f} Tf "
                f"({_pdf_escape(text)}) Tj".encode("latin-1")
            )
        parts.append(b"ET")
        streams.append(b"\n".join(parts))

    return _assemble_pdf(streams)


def _assemble_pdf(streams: list[bytes]) -> bytes:
    """Assemble N page objects + content streams + two fonts into a valid PDF with a
    byte-accurate xref table. Object numbering: 1 catalog, 2 pages, then per page
    ``3 + 2i`` (page) and ``4 + 2i`` (content), then the two font objects."""
    n = len(streams)
    font_regular = 3 + 2 * n
    font_bold = font_regular + 1
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode("latin-1"),
    ]
    for i, stream in enumerate(streams):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_W:.0f} {_PAGE_H:.0f}] "
            f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> "
            f"/Contents {4 + 2 * i} 0 R >>".encode("latin-1")
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode("latin-1") + b" >>\nstream\n"
            + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

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
