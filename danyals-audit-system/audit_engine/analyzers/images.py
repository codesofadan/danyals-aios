"""What format a page's images are in, and whether anything modern is offered.

WHAT THESE CAN AND CANNOT SEE. The crawler fetches HTML, not the images
referenced by it, so neither check here knows how many bytes an image actually
weighs. Reporting a compression RATIO would require fetching every asset on
every page, which multiplies crawl cost by the number of images on the site.

So both checks answer the question the markup CAN answer: what format is being
served, and is a modern one offered alongside it. That is the decision an owner
acts on anyway - "convert these to WebP" is the fix, and it does not depend on
knowing the current file size to the byte. Where a claim would need the bytes,
these say so rather than estimating one.

Both return ``n_a`` on a page with no images. A page with nothing to compress is
not a page that compresses badly, and scoring it 0.0 would drag the media
subpoint down over every text-only page on the site.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.registry import check
from audit_engine.crawlers.basic import CrawledPage

#: Formats that carry no useful compression for photographic web content. BMP
#: and TIFF are effectively raw; a photo shipped as either is the single largest
#: image win available on a page.
UNCOMPRESSED = frozenset({"bmp", "tif", "tiff"})

#: Lossy/lossless formats that compress, but predate the modern codecs.
LEGACY = frozenset({"jpg", "jpeg", "png", "gif"})

#: Google's own image-format guidance names WebP and AVIF as the formats to
#: prefer over JPEG and PNG. Source: web.dev "Serve images in modern formats".
MODERN = frozenset({"webp", "avif"})

#: JUDGEMENT: at least half the images on a page should be in a modern format
#: before the page counts as converted. There is no published threshold - Google
#: says "use modern formats", not "use them for N%" - so this is an adopted line,
#: chosen because a page where most images are still legacy has not been done.
MODERN_SHARE_TARGET = 0.5

_EXT = re.compile(r"\.([a-z0-9]{2,5})(?:[?#]|$)", re.I)
_PICTURE = re.compile(r"<picture\b", re.I)
_SRCSET_MODERN = re.compile(r'type\s*=\s*["\']image/(webp|avif)["\']', re.I)


def _ext(src: str) -> str:
    """The format a URL claims, or "" when it claims none.

    Query strings are stripped first: `hero.png?v=3` is a PNG, and a CDN path
    like `/img/1234/hero` claims nothing at all rather than claiming to be its
    last path segment.
    """
    path = urlparse(src or "").path
    m = _EXT.search(path)
    return m.group(1).lower() if m else ""


def _formats(page: CrawledPage) -> dict[str, int]:
    out: dict[str, int] = {}
    parsed = page.parsed
    for img in (parsed.images if parsed else []):
        ext = _ext(img.src)
        if ext:
            out[ext] = out.get(ext, 0) + 1
    return out


def _no_images(what: str) -> Verdict:
    return Verdict(
        status="n_a", score=0.0, severity="info", confidence=1.0,
        evidence={"reason": f"this page has no images, so there is nothing to {what}"},
    )


@check("ON-070", scope="page_http")
def compression(page: CrawledPage) -> Verdict:
    """ON-070 - are images served in a format that compresses?"""
    formats = _formats(page)
    total = sum(formats.values())
    if not total:
        return _no_images("compress")

    raw = sum(n for e, n in formats.items() if e in UNCOMPRESSED)
    legacy = sum(n for e, n in formats.items() if e in LEGACY)
    modern = sum(n for e, n in formats.items() if e in MODERN)
    share = modern / total
    ev = {
        "images_on_page": total,
        "modern_format": modern,
        "legacy_format": legacy,
        "uncompressed_format": raw,
        "formats_seen": ", ".join(f"{e} x{n}" for e, n in sorted(formats.items())),
    }

    if raw:
        return Verdict(
            status="fail", score=1.0, severity="major", confidence=1.0, evidence=ev,
            remediation=(
                f"{raw} of {total} images are served as BMP or TIFF, which apply no "
                "useful compression. Convert them to WebP; this is normally the "
                "largest single reduction available on a page."
            ),
        )
    if share >= MODERN_SHARE_TARGET:
        return Verdict(
            status="pass", score=10.0, severity="info", confidence=1.0, evidence=ev,
        )
    return Verdict(
        status="warn", score=5.0, severity="major", confidence=1.0, evidence=ev,
        remediation=(
            f"{legacy} of {total} images are still JPEG, PNG or GIF. Convert them to "
            "WebP and serve the originals as a fallback, so older browsers keep "
            "working while everything current downloads less."
        ),
    )


@check("TECH-090", scope="page_http")
def webp_support(page: CrawledPage) -> Verdict:
    """TECH-090 - is a modern format offered, and is there a fallback for it?

    Offering WebP through `<picture><source type="image/webp">` is materially
    different from linking a `.webp` directly: the first degrades on a browser
    that cannot decode it, the second shows a broken image. So a page that has
    adopted WebP WITHOUT a fallback is reported separately rather than passed.
    """
    formats = _formats(page)
    total = sum(formats.values())
    if not total:
        return _no_images("convert")

    modern = sum(n for e, n in formats.items() if e in MODERN)
    html = page.html or ""
    has_picture = bool(_PICTURE.search(html))
    has_typed_source = bool(_SRCSET_MODERN.search(html))
    ev = {
        "images_on_page": total,
        "modern_format": modern,
        "uses_picture_element": "yes" if has_picture else "no",
        "declares_a_modern_source_type": "yes" if has_typed_source else "no",
    }

    if modern and has_typed_source:
        return Verdict(status="pass", score=10.0, severity="info",
                       confidence=1.0, evidence=ev)
    if modern:
        return Verdict(
            status="warn", score=6.0, severity="minor", confidence=1.0, evidence=ev,
            remediation=(
                "WebP or AVIF images are served directly rather than through a "
                '<picture> element with <source type="image/webp">. Wrap them so a '
                "browser that cannot decode the format falls back to the original "
                "instead of showing a broken image."
            ),
        )
    return Verdict(
        status="warn", score=4.0, severity="minor", confidence=1.0, evidence=ev,
        remediation=(
            f"None of the {total} images on this page use WebP or AVIF. Serving them "
            'through <picture> with a <source type="image/webp"> keeps every browser '
            "working and cuts image weight substantially."
        ),
    )
