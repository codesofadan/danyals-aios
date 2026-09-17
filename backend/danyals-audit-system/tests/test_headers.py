"""Response-header checks: every branch, including n_a.

A check that cannot reach n_a will score a page it never measured, and because
the model is score = 100 x (1 - failed/ran), a fabricated fail is strictly
worse than an honest "not measured".
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from audit_engine.analyzers import headers as hdr
from audit_engine.analyzers.registry import registered


@dataclass
class FakeParsed:
    canonical: str | None = None
    meta_robots: str | None = None


@dataclass
class FakePage:
    url: str = "https://example.com/"
    final_url: str = "https://example.com/"
    http_status: int = 200
    response_ms: int = 200
    content_type: str | None = "text/html; charset=utf-8"
    bytes_size: int = 50_000
    http_version: str | None = "HTTP/2"
    headers: dict = field(default_factory=dict)
    parsed: FakeParsed | None = None


def page(**kw):
    hdrs = {"content-type": "text/html; charset=utf-8", "date": "Mon, 25 Aug 2026 00:00:00 GMT"}
    hdrs.update(kw.pop("headers", {}))
    return FakePage(headers=hdrs, **kw)


UNFETCHED = FakePage(headers={}, http_status=0)

ALL_CHECKS = [
    hdr.check_compression, hdr.check_gzip, hdr.check_brotli, hdr.check_browser_caching,
    hdr.check_https_transport, hdr.check_server_response, hdr.check_server_latency,
    hdr.check_http3, hdr.check_header_response_validation, hdr.check_content_type,
    hdr.check_indexability, hdr.check_canonical_conflict,
]


# --- the n_a contract, for every check --------------------------------------

@pytest.mark.parametrize("fn", ALL_CHECKS, ids=lambda f: f.__name__)
def test_a_page_that_was_never_fetched_is_n_a_not_a_failure(fn):
    v = fn(UNFETCHED)
    assert v.status == "n_a", f"{fn.__name__} scored a page it never received"
    assert v.confidence == 0.0


@pytest.mark.parametrize("fn", ALL_CHECKS, ids=lambda f: f.__name__)
def test_no_check_raises_on_a_bare_page(fn):
    fn(FakePage(headers={"content-type": "text/html"}))


@pytest.mark.parametrize("fn", ALL_CHECKS, ids=lambda f: f.__name__)
def test_every_verdict_is_well_formed(fn):
    for p in (UNFETCHED, page(), page(headers={"content-encoding": "br"})):
        v = fn(p)
        assert v.status in {"pass", "warn", "fail", "n_a"}
        assert 0.0 <= v.score <= 10.0
        assert 0.0 <= v.confidence <= 1.0
        assert isinstance(v.evidence, dict)
        if v.status == "n_a":
            assert not v.remediation, f"{fn.__name__} gives a fix for an unmeasured check"


# --- compression ------------------------------------------------------------

def test_compression_passes_when_encoded():
    assert hdr.check_compression(page(headers={"content-encoding": "gzip"})).status == "pass"


def test_compression_fails_on_a_large_uncompressed_response():
    v = hdr.check_compression(page(bytes_size=400_000))
    assert v.status == "fail" and v.severity == "major"
    assert "400,000" in v.remediation


def test_compression_is_n_a_on_a_response_too_small_to_benefit():
    """Below ~1.5KB gzip can make the response bigger, so absence is not a defect."""
    assert hdr.check_compression(page(bytes_size=800)).status == "n_a"


def test_brotli_warns_when_only_gzip_is_present():
    v = hdr.check_brotli(page(headers={"content-encoding": "gzip"}))
    assert v.status == "warn" and "Brotli" in v.remediation


def test_brotli_passes_on_br():
    assert hdr.check_brotli(page(headers={"content-encoding": "br"})).status == "pass"


def test_gzip_accepts_brotli_because_it_supersedes_gzip():
    assert hdr.check_gzip(page(headers={"content-encoding": "br"})).status == "pass"


# --- caching ----------------------------------------------------------------

def test_caching_fails_with_no_policy_at_all():
    v = hdr.check_browser_caching(page())
    assert v.status == "fail"


def test_caching_warns_when_only_a_validator_is_present():
    v = hdr.check_browser_caching(page(headers={"etag": '"abc"'}))
    assert v.status == "warn" and "round trip" in v.remediation


def test_a_static_asset_wants_a_year():
    good = page(final_url="https://example.com/app.a1b2.js",
                headers={"cache-control": "public, max-age=31536000, immutable"})
    assert hdr.check_browser_caching(good).status == "pass"
    short = page(final_url="https://example.com/app.a1b2.js",
                 headers={"cache-control": "public, max-age=600"})
    assert hdr.check_browser_caching(short).status == "warn"


def test_html_cached_for_too_long_is_flagged():
    v = hdr.check_browser_caching(page(headers={"cache-control": "public, max-age=604800"}))
    assert v.status == "warn"
    assert "correction" in v.remediation


def test_html_with_a_short_max_age_passes():
    assert hdr.check_browser_caching(page(headers={"cache-control": "public, max-age=600"})).status == "pass"


# --- transport security -----------------------------------------------------

def test_plain_http_is_critical():
    v = hdr.check_https_transport(page(final_url="http://example.com/"))
    assert v.status == "fail" and v.severity == "critical" and v.score == 0.0


def test_https_without_hsts_warns():
    assert hdr.check_https_transport(page()).status == "warn"


def test_https_with_a_year_of_hsts_passes():
    v = hdr.check_https_transport(page(headers={"strict-transport-security": "max-age=31536000"}))
    assert v.status == "pass"


def test_a_short_hsts_max_age_is_flagged():
    v = hdr.check_https_transport(page(headers={"strict-transport-security": "max-age=300"}))
    assert v.status == "warn" and "31536000" in v.remediation


# --- server response --------------------------------------------------------

@pytest.mark.parametrize("ms,expected", [(200, "pass"), (1200, "warn"), (5638, "fail")])
def test_ttfb_bands_follow_googles_published_thresholds(ms, expected):
    assert hdr.check_server_response(page(response_ms=ms)).status == expected


def test_server_response_reports_the_number_it_measured():
    v = hdr.check_server_response(page(response_ms=5638))
    assert v.evidence["response_ms"] == 5638
    assert "5,638" in v.remediation


def test_server_response_is_n_a_with_no_timing():
    assert hdr.check_server_response(page(response_ms=0)).status == "n_a"


def test_latency_is_n_a_when_the_server_publishes_no_timing_signal():
    """Without Server-Timing or a cache header, origin time cannot be separated
    from network time, and guessing would be a fabricated measurement."""
    assert hdr.check_server_latency(page()).status == "n_a"


def test_latency_passes_on_a_cache_hit():
    v = hdr.check_server_latency(page(headers={"cf-cache-status": "HIT"}, response_ms=2500))
    assert v.status == "pass"


def test_latency_fails_on_a_slow_origin_miss():
    v = hdr.check_server_latency(page(headers={"cf-cache-status": "MISS"}, response_ms=2500))
    assert v.status == "fail"


# --- protocol ---------------------------------------------------------------

def test_http3_passes_on_the_wire():
    assert hdr.check_http3(page(http_version="HTTP/3")).status == "pass"


def test_http3_passes_when_advertised_by_alt_svc():
    v = hdr.check_http3(page(headers={"alt-svc": 'h3=":443"; ma=86400'}))
    assert v.status == "pass" and v.evidence["advertises_h3"] is True


def test_http3_warns_when_absent():
    assert hdr.check_http3(page(http_version="HTTP/1.1")).status == "warn"


# --- header hygiene ---------------------------------------------------------

def test_a_version_disclosing_server_header_is_flagged():
    v = hdr.check_header_response_validation(page(headers={"server": "nginx/1.18.0"}))
    assert v.status == "warn"
    assert "nginx/1.18.0" in v.remediation


def test_x_powered_by_is_flagged():
    v = hdr.check_header_response_validation(page(headers={"x-powered-by": "PHP/7.4.3"}))
    assert v.status == "warn"


def test_a_clean_response_passes():
    assert hdr.check_header_response_validation(page(headers={"server": "cloudflare"})).status == "pass"


def test_an_error_status_is_a_failure():
    v = hdr.check_header_response_validation(page(http_status=503))
    assert v.status == "fail"


def test_html_without_a_charset_warns():
    v = hdr.check_content_type(page(headers={"content-type": "text/html"}))
    assert v.status == "warn" and "charset" in v.remediation


def test_content_type_passes_with_charset_and_nosniff():
    v = hdr.check_content_type(page(headers={"x-content-type-options": "nosniff"}))
    assert v.status == "pass"


# --- indexability -----------------------------------------------------------

def test_a_header_noindex_is_critical_and_invisible_in_the_html():
    v = hdr.check_indexability(page(headers={"x-robots-tag": "noindex, nofollow"}))
    assert v.status == "fail" and v.severity == "critical"
    assert "only the response header" in v.remediation


def test_x_robots_tag_none_is_treated_as_noindex():
    assert hdr.check_indexability(page(headers={"x-robots-tag": "none"})).status == "fail"


def test_meta_noindex_is_caught_too():
    v = hdr.check_indexability(page(parsed=FakeParsed(meta_robots="noindex")))
    assert v.status == "fail"


def test_an_indexable_page_passes():
    assert hdr.check_indexability(page(parsed=FakeParsed())).status == "pass"


# --- canonical --------------------------------------------------------------

def test_a_header_and_html_canonical_that_disagree_is_critical():
    p = page(headers={"link": '<https://example.com/a>; rel="canonical"'},
             parsed=FakeParsed(canonical="https://example.com/b"))
    v = hdr.check_canonical_conflict(p)
    assert v.status == "fail" and v.severity == "critical"


def test_canonicals_that_differ_only_by_a_trailing_slash_do_not_conflict():
    """They normalise to the same page, so calling this a conflict would be a
    false positive on most of the web."""
    p = page(headers={"link": '<https://example.com/a/>; rel="canonical"'},
             parsed=FakeParsed(canonical="https://example.com/a"))
    assert hdr.check_canonical_conflict(p).status == "pass"


def test_no_canonical_anywhere_warns():
    assert hdr.check_canonical_conflict(page(parsed=FakeParsed())).status == "warn"


# --- registration -----------------------------------------------------------

def test_every_check_in_this_module_is_registered_at_page_http_scope():
    import audit_engine.analyzers.headers  # noqa: F401

    reg = registered()
    for cid in ("TECH-006", "TECH-021", "TECH-050", "TECH-051", "TECH-052",
                "TECH-053", "TECH-055", "TECH-072", "TECH-095", "TECH-096",
                "TECH-098", "TECH-099"):
        assert cid in reg, f"{cid} is not registered"
        assert reg[cid].scope == "page_http"
