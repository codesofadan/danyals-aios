"""The three checks that only ever needed writing.

ON-070, TECH-082 and TECH-090 sat under `not_yet_built` with the reason "needs an
input we do not fetch". They did not: all three read the crawled HTML and the
response headers this audit already collects. They were simply unwritten.

The branch that gets the most attention here is `n_a`. A page with no images is
not a page that compresses badly, and a page whose fetch failed is not a page
carrying malware - scoring either as a failure at 0.0 is the most common way an
audit lies, and `aggregator` drops `n_a` from the weighted mean precisely so that
"nothing to say" costs a pillar nothing.
"""

from __future__ import annotations

import pytest

from audit_engine.analyzers import images, security
from audit_engine.crawlers.basic import CrawledPage
from audit_engine.parsers.html import Image, ParsedHTML


def _img(src: str) -> Image:
    return Image(src=src, alt="x", width=None, height=None, loading=None, is_lazy=False)


def _page(*, srcs: list[str] | None = None, html: str = "<html></html>") -> CrawledPage:
    parsed = ParsedHTML(url="https://example.com/p")
    parsed.images = [_img(s) for s in (srcs or [])]
    return CrawledPage(
        url="https://example.com/p", final_url="https://example.com/p",
        http_status=200, response_ms=100, content_type="text/html",
        bytes_size=len(html), html=html, parsed=parsed,
    )


# ------------------------------------------------------------------ ON-070

def test_a_page_with_no_images_is_not_a_compression_failure():
    v = images.compression(_page())
    assert v.status == "n_a"
    assert "no images" in v.evidence["reason"]


def test_an_uncompressed_format_fails_and_names_the_count():
    v = images.compression(_page(srcs=["/a.bmp", "/b.jpg", "/c.jpg"]))
    assert v.status == "fail"
    assert v.severity == "major"
    assert "1 of 3" in v.remediation


def test_a_mostly_modern_page_passes():
    v = images.compression(_page(srcs=["/a.webp", "/b.avif", "/c.jpg"]))
    assert v.status == "pass"
    assert v.evidence["modern_format"] == 2


def test_a_legacy_page_warns_rather_than_fails():
    # JPEG is compressed; it is just not the best available. That is a warn.
    v = images.compression(_page(srcs=["/a.jpg", "/b.png", "/c.gif"]))
    assert v.status == "warn"
    assert v.evidence["legacy_format"] == 3


def test_a_query_string_does_not_hide_the_format():
    v = images.compression(_page(srcs=["/hero.png?v=3", "/x.png#a"]))
    assert v.evidence["formats_seen"] == "png x2"


def test_an_extensionless_cdn_url_claims_nothing():
    # `/img/1234/hero` must not be read as a "hero" format.
    v = images.compression(_page(srcs=["/img/1234/hero"]))
    assert v.status == "n_a"


# ----------------------------------------------------------------- TECH-090

def test_webp_without_a_fallback_is_reported_separately_from_having_none():
    direct = images.webp_support(_page(srcs=["/a.webp"], html="<img src=/a.webp>"))
    assert direct.status == "warn"
    # It has to name the fix, not just the problem.
    assert "<picture>" in direct.remediation

    proper = images.webp_support(_page(
        srcs=["/a.webp"],
        html='<picture><source type="image/webp" srcset="/a.webp"><img src="/a.jpg"></picture>',
    ))
    assert proper.status == "pass"


def test_no_modern_format_at_all_warns():
    v = images.webp_support(_page(srcs=["/a.jpg", "/b.png"]))
    assert v.status == "warn"
    assert v.evidence["modern_format"] == 0


def test_webp_support_is_n_a_without_images():
    assert images.webp_support(_page()).status == "n_a"


# ----------------------------------------------------------------- TECH-082

_CLEAN = """<html><head><script src="https://example.com/app.js"></script></head>
<body><h1>Hello</h1><script>window.dataLayer=window.dataLayer||[];</script></body></html>"""


def test_a_clean_page_passes_but_never_claims_certainty():
    v = security.malware(_page(html=_CLEAN))
    assert v.status == "pass"
    # A pattern scan cannot prove absence, and the confidence has to say so.
    assert v.confidence <= 0.6
    assert "not an antivirus" in v.evidence["method"]


def test_one_signal_asks_rather_than_accuses():
    html = _CLEAN.replace("<h1>Hello</h1>", '<iframe src="//x.test/a" width="0" height="0"></iframe>')
    v = security.malware(_page(html=html))
    assert v.status == "warn"
    assert "hidden_iframe" in v.evidence["signals_found"]
    # The word that must not appear on one signal.
    assert "malware" not in (v.remediation or "").lower()


def test_two_independent_signals_accuse():
    html = _CLEAN.replace(
        "<h1>Hello</h1>",
        '<iframe src="//x.test/a" width="0" height="0"></iframe>'
        "<script>eval(atob('ZG9jdW1lbnQ='));</script>",
    )
    v = security.malware(_page(html=html))
    assert v.status == "fail"
    assert v.severity == "critical"
    assert v.evidence["signal_count"] >= 2
    # Even accusing, it says how it knows and asks for confirmation.
    assert "confirm before acting" in v.remediation


def test_an_inline_data_uri_image_is_not_obfuscation():
    # The main innocent source of long base64. Attributes are stripped before
    # the scan precisely so a hero image does not read as a payload.
    html = _CLEAN.replace("<h1>Hello</h1>", '<img src="data:image/png;base64,' + "A" * 400 + '">')
    v = security.malware(_page(html=html))
    assert v.status == "pass", v.evidence


def test_a_page_that_returned_no_html_is_not_scanned():
    v = security.malware(_page(html=""))
    assert v.status == "n_a"
    assert "nothing could be scanned" in v.evidence["reason"]


@pytest.mark.parametrize("snippet", [
    "<script>document.write(unescape('%3Cscript'));</script>",
    "<script>new Function(atob('eA=='))();</script>",
])
def test_each_decode_and_run_idiom_is_recognised(snippet):
    v = security.malware(_page(html=_CLEAN.replace("<h1>Hello</h1>", snippet)))
    assert v.status in ("warn", "fail")
    assert v.evidence["signal_count"] >= 1
