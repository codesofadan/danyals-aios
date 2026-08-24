"""P0-3 REGRESSION GUARD: the PDF deliverable must contain the ARTICLE.

Prevented defect: `_minimal_pdf(title)` produced a one-page PDF whose entire visible
content was the title string, and `_publish_artifact` handed that key to
`_emit_content_deliverable` in preference to the Markdown. The client downloaded a
near-blank page and the article they paid for was never delivered.

It survived because the module docstring framed it as a deliberate staging decision
("enough for a real, downloadable artifact ... a later chunk can swap in a full
renderer"), and because the only assertions on it were that a file existed.

So these tests assert on the PDF's CONTENT and STRUCTURE, not its existence.
"""

from __future__ import annotations

import re

import pytest

from app.services.content_artifacts import _strip_inline, _wrap, render_pdf

_BODY_SENTINEL = "Zephyrine calibration torque"
_ARTICLE = f"""# Roof Repair in Austin

{_BODY_SENTINEL} matters when a crew re-seats flashing on a low-slope roof.

## What it costs

- A tear-off runs longer than an overlay
- Decking damage is found after the tear-off

![crew on a roof](https://cdn.example.com/roof.jpg)

See our [pricing guide](https://example.com/pricing) for the full breakdown.
"""


def _extracted_text(pdf: bytes) -> str:
    """Pull every text-showing operand out of the content streams."""
    return " ".join(m.decode("latin-1") for m in re.findall(rb"\((.*?)\) Tj", pdf))


# --------------------------------------------------------------------------- #
# 1 - the article is actually in the file
# --------------------------------------------------------------------------- #
def test_pdf_contains_the_body_not_just_the_title() -> None:
    text = _extracted_text(render_pdf(_ARTICLE, title="Roof Repair in Austin"))
    assert "Roof Repair in Austin" in text
    assert _BODY_SENTINEL in text, "the body prose never reached the PDF"
    assert "What it costs" in text, "headings are missing"
    assert "tear-off runs longer" in text, "list items are missing"


def test_pdf_is_substantially_larger_than_a_title_page() -> None:
    """The original defect is expressible as a size: a title-only page. A long article
    must not render to roughly the same byte count as its own headline."""
    long_article = _ARTICLE + ("Additional prose for the body. " * 400)
    full = len(_extracted_text(render_pdf(long_article, title="T")))
    title_only = len(_extracted_text(render_pdf("", title="T")))
    assert full > title_only * 20, (full, title_only)


def test_long_article_paginates() -> None:
    pdf = render_pdf("Body sentence here. " * 1200, title="Long")
    assert pdf.count(b"/Type /Page ") >= 3, "a 1200-sentence body rendered on <3 pages"


# --------------------------------------------------------------------------- #
# 2 - the file is STRUCTURALLY valid (a wrong xref silently breaks readers)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "markdown",
    ["", "# Only a heading", _ARTICLE, "Body. " * 2000, "Ünïcödé — “smart” quotes …"],
)
def test_xref_offsets_are_byte_accurate(markdown: str) -> None:
    """Every xref entry must point at the exact first byte of `N 0 obj`. This is the
    part a reader validates and a naive assembler gets wrong."""
    pdf = render_pdf(markdown, title="T")
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")

    xref_pos = int(pdf[pdf.rindex(b"startxref"):].split(b"\n")[1])
    assert pdf[xref_pos : xref_pos + 4] == b"xref"

    lines = pdf[xref_pos:].split(b"\n")
    count = int(lines[1].split()[1])
    for i in range(1, count):
        offset = int(lines[i + 2].split()[0])
        assert pdf[offset:].startswith(f"{i} 0 obj".encode()), (
            f"xref entry {i} points at {pdf[offset:offset + 24]!r}"
        )


def test_non_latin1_input_never_raises() -> None:
    """The renderer sits on the publish path, so no input may crash it. Latin-1 is the
    encoding of the literal strings; anything outside it must be transliterated or
    dropped, never propagated as a UnicodeEncodeError."""
    pdf = render_pdf("Café — naïve “quotes” … 日本語 🎉", title="Ünïcödé")
    assert pdf.startswith(b"%PDF-")
    text = _extracted_text(pdf)
    assert "Caf" in text and "-" in text  # em dash transliterated, not dropped silently


@pytest.mark.parametrize("body", ["", None])
def test_empty_body_still_yields_a_valid_pdf(body: str | None) -> None:
    """A publish must never fail because the deliverable had nothing to render."""
    pdf = render_pdf(body, title="Fallback")
    assert pdf.startswith(b"%PDF-")
    assert "Fallback" in _extracted_text(pdf)


# --------------------------------------------------------------------------- #
# 3 - the markdown flattening keeps information a printed page cannot recover
# --------------------------------------------------------------------------- #
def test_links_keep_their_destination() -> None:
    """A PDF reader cannot click. Dropping the href would lose the reference entirely."""
    out = _strip_inline("see the [pricing guide](https://example.com/pricing) now")
    assert "pricing guide" in out and "https://example.com/pricing" in out


def test_images_render_as_a_captioned_reference_not_a_silent_drop() -> None:
    out = _strip_inline("![a crew on a roof](https://cdn.example.com/roof.jpg)")
    assert "a crew on a roof" in out and "roof.jpg" in out


def test_wrap_never_drops_an_over_long_token() -> None:
    """A bare URL is longer than the column. It must occupy its own line, not vanish."""
    url = "https://example.com/" + "x" * 200
    lines = _wrap(f"see {url} here", size=10.5)
    assert url in " ".join(lines)
