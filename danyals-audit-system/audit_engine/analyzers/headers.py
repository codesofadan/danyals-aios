"""Checks that read the HTTP response rather than the HTML body.

The crawler always had ``resp.headers`` - it read content-type off them - but
``CrawledPage`` never stored them, so sixteen declared checks had no data to
run on. Wave 2 stores them (credential headers removed) and implements the
checks that need nothing else.

Every numeric threshold below carries its source. Where no primary source
exists the constant is marked JUDGEMENT with a sentence saying why, because
"industry standard" is usually community lore repeated until it sounds
official.
"""

from __future__ import annotations

import re
from typing import Any

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.registry import check

# web.dev/ttfb - Google's published Time to First Byte bands. These are the
# same numbers PageSpeed uses, so a client sees one story from two tools.
TTFB_GOOD_MS = 800
TTFB_POOR_MS = 1800

# RFC 9111 s5.2.2.1. A year is the maximum any cache is required to honour and
# is Google's recommendation for fingerprinted static assets.
CACHE_STATIC_GOOD_S = 31_536_000
# JUDGEMENT: HTML is not fingerprinted, so a long max-age serves stale pages
# after a fix. An hour is short enough to publish same-day and long enough to
# absorb a traffic spike.
CACHE_HTML_MAX_REASONABLE_S = 3600

_MAX_AGE = re.compile(r"max-age\s*=\s*(\d+)", re.IGNORECASE)
_STATIC_EXT = re.compile(r"\.(css|js|mjs|woff2?|ttf|otf|png|jpe?g|gif|webp|avif|svg|ico)$", re.I)


def _h(cp: Any, name: str) -> str:
    return (getattr(cp, "headers", {}) or {}).get(name, "") or ""


def _is_html(cp: Any) -> bool:
    return "html" in (_h(cp, "content-type") or getattr(cp, "content_type", "") or "").lower()


def _fetched(cp: Any) -> bool:
    """A page we never actually received cannot be measured."""
    return bool(getattr(cp, "headers", None)) and int(getattr(cp, "http_status", 0) or 0) > 0


def _na(reason: str, **ev: Any) -> Verdict:
    return Verdict("n_a", 0.0, "info", 0.0, {"reason": reason, **ev})


# --------------------------------------------------------------------------
# Compression
# --------------------------------------------------------------------------

@check("TECH-050", scope="page_http")
def check_compression(cp: Any) -> Verdict:
    """TECH-050 - is the response compressed at all?"""
    if not _fetched(cp):
        return _na("page was not fetched")
    enc = _h(cp, "content-encoding").lower()
    size = int(getattr(cp, "bytes_size", 0) or 0)
    ev = {"content_encoding": enc or None, "bytes": size}
    if enc:
        return Verdict("pass", 10.0, "info", 1.0, ev)
    # JUDGEMENT: below ~1.5 KB a compressed response can be LARGER than the
    # original once the gzip header and dictionary are counted, so absence of
    # compression on a tiny response is not a defect.
    if size < 1500:
        return Verdict("n_a", 0.0, "info", 0.8,
                       {**ev, "reason": "response too small for compression to help"})
    return Verdict(
        "fail", 2.0, "major", 1.0, ev,
        f"Response is {size:,} bytes and uncompressed. Enable gzip or Brotli; "
        f"text compresses roughly 70-80%, so this page would transfer in about "
        f"{size // 4:,} bytes.",
    )


@check("TECH-051", scope="page_http")
def check_gzip(cp: Any) -> Verdict:
    """TECH-051 - gzip specifically. Brotli counts: it supersedes gzip."""
    if not _fetched(cp):
        return _na("page was not fetched")
    enc = _h(cp, "content-encoding").lower()
    ev = {"content_encoding": enc or None}
    if "gzip" in enc or "br" in enc or "zstd" in enc:
        return Verdict("pass", 10.0, "info", 1.0, ev)
    if not enc:
        return Verdict("fail", 2.0, "major", 1.0, ev,
                       "No compression negotiated. Enable gzip at minimum.")
    return Verdict("warn", 6.0, "minor", 1.0, ev,
                   f"Response uses {enc!r} rather than gzip, Brotli or zstd.")


@check("TECH-052", scope="page_http")
def check_brotli(cp: Any) -> Verdict:
    """TECH-052 - Brotli. Google reports 15-20% smaller than gzip for text."""
    if not _fetched(cp):
        return _na("page was not fetched")
    enc = _h(cp, "content-encoding").lower()
    ev = {"content_encoding": enc or None}
    if "br" in enc.split(",")[0] or enc.strip() == "br":
        return Verdict("pass", 10.0, "info", 1.0, ev)
    if "gzip" in enc:
        return Verdict("warn", 7.0, "minor", 1.0, ev,
                       "gzip is enabled but Brotli is not. Brotli transfers text "
                       "roughly 15-20% smaller and is supported by every current browser.")
    return Verdict("fail", 3.0, "minor", 1.0, ev,
                   "Neither Brotli nor gzip is enabled.")


# --------------------------------------------------------------------------
# Caching
# --------------------------------------------------------------------------

@check("TECH-053", scope="page_http")
def check_browser_caching(cp: Any) -> Verdict:
    """TECH-053 - a cache policy must exist and must suit the content type."""
    if not _fetched(cp):
        return _na("page was not fetched")
    cc = _h(cp, "cache-control").lower()
    expires = _h(cp, "expires")
    etag = _h(cp, "etag")
    last_mod = _h(cp, "last-modified")
    m = _MAX_AGE.search(cc)
    max_age = int(m.group(1)) if m else None
    static = bool(_STATIC_EXT.search(getattr(cp, "final_url", "") or ""))
    ev = {"cache_control": cc or None, "max_age_seconds": max_age,
          "expires": expires or None, "has_etag": bool(etag),
          "has_last_modified": bool(last_mod), "treated_as_static": static}

    if not cc and not expires:
        if etag or last_mod:
            return Verdict("warn", 6.0, "minor", 1.0, ev,
                           "No Cache-Control. The validator (ETag/Last-Modified) still "
                           "saves bandwidth, but every visit costs a round trip. Add "
                           "Cache-Control to avoid the request entirely.")
        return Verdict("fail", 2.0, "major", 1.0, ev,
                       "No Cache-Control, Expires, ETag or Last-Modified. Every asset "
                       "is re-downloaded in full on every visit.")
    if "no-store" in cc:
        return Verdict("warn", 5.0, "minor", 1.0, ev,
                       "Cache-Control: no-store prevents all caching. Correct for a "
                       "logged-in page, wasteful for public content.")
    if static:
        if max_age is not None and max_age >= CACHE_STATIC_GOOD_S:
            return Verdict("pass", 10.0, "info", 1.0, ev)
        if max_age is not None:
            return Verdict("warn", 6.0, "minor", 1.0, ev,
                           f"Static asset cached for {max_age:,}s. Fingerprinted assets "
                           f"should use max-age=31536000 (one year) with immutable.")
        return Verdict("warn", 5.0, "minor", 1.0, ev, "Static asset has no max-age.")
    if max_age is not None and max_age > CACHE_HTML_MAX_REASONABLE_S and "no-cache" not in cc:
        return Verdict("warn", 6.0, "minor", 1.0, ev,
                       f"HTML is cached for {max_age:,}s. A published correction will not "
                       f"reach visitors who already have the page until it expires.")
    return Verdict("pass", 10.0, "info", 1.0, ev)


# --------------------------------------------------------------------------
# Transport security
# --------------------------------------------------------------------------

@check("TECH-055", scope="page_http")
def check_https_transport(cp: Any) -> Verdict:
    """TECH-055 - HTTPS end to end, plus HSTS."""
    if not _fetched(cp):
        return _na("page was not fetched")
    final = (getattr(cp, "final_url", "") or "").lower()
    hsts = _h(cp, "strict-transport-security")
    m = _MAX_AGE.search(hsts)
    hsts_age = int(m.group(1)) if m else None
    ev = {"final_url_scheme": final.split(":", 1)[0] or None,
          "hsts": hsts or None, "hsts_max_age": hsts_age}
    if not final.startswith("https://"):
        return Verdict("fail", 0.0, "critical", 1.0, ev,
                       "Page is served over plain HTTP. Browsers mark it "
                       "'Not secure' and Google has used HTTPS as a ranking signal "
                       "since 2014.")
    if not hsts:
        return Verdict("warn", 7.0, "minor", 1.0, ev,
                       "HTTPS is in use but Strict-Transport-Security is absent, so the "
                       "first visit of each session can still be downgraded. Add "
                       "Strict-Transport-Security: max-age=31536000.")
    # RFC 6797 s7.2: a max-age under six months is too short to survive a
    # typical visit interval, and preload lists require a year.
    if hsts_age is not None and hsts_age < 15_768_000:
        return Verdict("warn", 8.0, "minor", 1.0, ev,
                       f"HSTS max-age is {hsts_age:,}s. Raise it to 31536000 (one year).")
    return Verdict("pass", 10.0, "info", 1.0, ev)


# --------------------------------------------------------------------------
# Server behaviour
# --------------------------------------------------------------------------

@check("TECH-072", scope="page_http")
def check_server_response(cp: Any) -> Verdict:
    """TECH-072 - time to first byte, against Google's published bands.

    This id spent months carrying an interaction_to_next_paint measurement
    under the name "Server response analysis". It now measures what it says.
    """
    if not _fetched(cp):
        return _na("page was not fetched")
    ms = int(getattr(cp, "response_ms", 0) or 0)
    ev = {"response_ms": ms, "good_threshold_ms": TTFB_GOOD_MS,
          "poor_threshold_ms": TTFB_POOR_MS, "server": _h(cp, "server") or None}
    if ms <= 0:
        return _na("no timing recorded", **ev)
    if ms <= TTFB_GOOD_MS:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    if ms <= TTFB_POOR_MS:
        return Verdict("warn", 6.0, "major", 0.9, ev,
                       f"Server took {ms:,} ms to respond against Google's {TTFB_GOOD_MS} ms "
                       f"target. Every downstream metric starts late by that amount.")
    return Verdict("fail", 2.0, "critical", 0.9, ev,
                   f"Server took {ms:,} ms to respond, past Google's {TTFB_POOR_MS} ms "
                   f"'poor' threshold. This alone caps the page speed score.")


@check("TECH-099", scope="page_http")
def check_server_latency(cp: Any) -> Verdict:
    """TECH-099 - latency attributable to the origin rather than the network.

    Distinct from TECH-072: this reads the server's own timing headers when it
    publishes them, so a slow ORIGIN can be told from a slow connection.
    """
    if not _fetched(cp):
        return _na("page was not fetched")
    st = _h(cp, "server-timing")
    age = _h(cp, "age")
    cache_hdr = _h(cp, "x-cache") or _h(cp, "cf-cache-status") or _h(cp, "x-vercel-cache")
    total = int(getattr(cp, "response_ms", 0) or 0)
    ev = {"response_ms": total, "server_timing": st or None,
          "age": age or None, "cache_status": cache_hdr or None}
    if not st and not cache_hdr:
        return Verdict("n_a", 0.0, "info", 0.4,
                       {**ev, "reason": "server publishes no Server-Timing or cache header, "
                                        "so origin time cannot be separated from network time"})
    if cache_hdr and "hit" in cache_hdr.lower():
        return Verdict("pass", 10.0, "info", 0.8,
                       {**ev, "served_from_cache": True})
    if total > TTFB_POOR_MS:
        return Verdict("fail", 3.0, "major", 0.8, ev,
                       f"{total:,} ms with cache status {cache_hdr or 'unknown'!r}. "
                       f"Requests are reaching the origin rather than an edge cache.")
    if total > TTFB_GOOD_MS:
        return Verdict("warn", 6.0, "minor", 0.8, ev,
                       f"{total:,} ms, cache status {cache_hdr or 'unknown'!r}.")
    return Verdict("pass", 10.0, "info", 0.8, ev)


@check("TECH-098", scope="page_http")
def check_http3(cp: Any) -> Verdict:
    """TECH-098 - HTTP/3. Advertising it via Alt-Svc counts: that is how a
    browser discovers h3 on the first connection."""
    if not _fetched(cp):
        return _na("page was not fetched")
    ver = (getattr(cp, "http_version", "") or "").upper()
    alt = _h(cp, "alt-svc").lower()
    advertises = "h3" in alt
    ev = {"http_version": ver or None, "alt_svc": _h(cp, "alt-svc") or None,
          "advertises_h3": advertises}
    if "3" in ver.replace("HTTP/", ""):
        return Verdict("pass", 10.0, "info", 1.0, ev)
    if advertises:
        return Verdict("pass", 9.0, "info", 0.9, ev)
    return Verdict("warn", 6.0, "minor", 1.0, ev,
                   "No HTTP/3. It removes head-of-line blocking and speeds up "
                   "high-latency and mobile connections; most CDNs enable it with a switch.")


@check("TECH-095", scope="page_http")
def check_header_response_validation(cp: Any) -> Verdict:
    """TECH-095 - the response headers a page must have, and must not."""
    if not _fetched(cp):
        return _na("page was not fetched")
    problems: list[str] = []
    ctype = _h(cp, "content-type")
    if not ctype:
        problems.append("no Content-Type")
    if not _h(cp, "date"):
        problems.append("no Date header (required by RFC 9110 s6.6.1)")
    # A server that names its exact version hands an attacker a CVE lookup.
    server = _h(cp, "server")
    if server and re.search(r"\d+\.\d+", server):
        problems.append(f"Server header exposes a version: {server!r}")
    powered = _h(cp, "x-powered-by")
    if powered:
        problems.append(f"X-Powered-By exposes the stack: {powered!r}")
    status = int(getattr(cp, "http_status", 0) or 0)
    if status >= 400:
        problems.append(f"status {status}")
    ev = {"problems": problems, "status": status, "content_type": ctype or None,
          "server": server or None, "x_powered_by": powered or None}
    if not problems:
        return Verdict("pass", 10.0, "info", 1.0, ev)
    severe = any("no Content-Type" in p or "status" in p for p in problems)
    return Verdict(
        "fail" if severe else "warn",
        3.0 if severe else 7.0,
        "major" if severe else "minor",
        1.0, ev,
        "Response header problems: " + "; ".join(problems) + ".",
    )


@check("TECH-096", scope="page_http")
def check_content_type(cp: Any) -> Verdict:
    """TECH-096 - Content-Type must be present, correct, and declare a charset
    for text. Without a charset a browser guesses, and a wrong guess turns a
    page of copy into mojibake that Google indexes verbatim."""
    if not _fetched(cp):
        return _na("page was not fetched")
    ctype = _h(cp, "content-type")
    lower = ctype.lower()
    ev = {"content_type": ctype or None,
          "has_charset": "charset=" in lower,
          "nosniff": "nosniff" in _h(cp, "x-content-type-options").lower()}
    if not ctype:
        return Verdict("fail", 2.0, "major", 1.0, ev,
                       "No Content-Type. Browsers and crawlers must sniff the body to "
                       "guess what this page is.")
    if "html" in lower and "charset=" not in lower:
        return Verdict("warn", 6.0, "minor", 1.0, ev,
                       "Content-Type declares HTML but no charset. Add "
                       "'; charset=utf-8' so browsers stop guessing the encoding.")
    if not ev["nosniff"]:
        return Verdict("warn", 8.0, "minor", 1.0, ev,
                       "Content-Type is correct but X-Content-Type-Options: nosniff is "
                       "absent, so a browser may still override it.")
    return Verdict("pass", 10.0, "info", 1.0, ev)


# --------------------------------------------------------------------------
# Indexability and canonical, as the HEADERS declare them
# --------------------------------------------------------------------------

@check("TECH-006", scope="page_http")
def check_indexability(cp: Any) -> Verdict:
    """TECH-006 - X-Robots-Tag. A header noindex is invisible in the HTML, so
    it is the single easiest way to deindex a site by accident and the hardest
    to spot by looking at the page."""
    if not _fetched(cp):
        return _na("page was not fetched")
    xrobots = _h(cp, "x-robots-tag").lower()
    status = int(getattr(cp, "http_status", 0) or 0)
    parsed = getattr(cp, "parsed", None)
    meta = (getattr(parsed, "meta_robots", "") or "").lower() if parsed else ""
    ev = {"x_robots_tag": _h(cp, "x-robots-tag") or None,
          "meta_robots": meta or None, "status": status}
    if "noindex" in xrobots:
        return Verdict("fail", 0.0, "critical", 1.0, ev,
                       "X-Robots-Tag sends noindex, so this page is excluded from Google "
                       "entirely. The HTML gives no sign of it - only the response header does.")
    if status >= 400:
        return Verdict("fail", 0.0, "critical", 1.0, ev,
                       f"Page returns {status}, so it cannot be indexed.")
    if "none" in xrobots:
        return Verdict("fail", 0.0, "critical", 1.0, ev,
                       "X-Robots-Tag: none is equivalent to noindex, nofollow.")
    if "nofollow" in xrobots:
        return Verdict("warn", 5.0, "major", 1.0, ev,
                       "X-Robots-Tag sends nofollow, so no link on this page passes signal.")
    if "noindex" in meta:
        return Verdict("fail", 0.0, "critical", 1.0, ev,
                       "The page carries meta robots noindex and is excluded from Google.")
    return Verdict("pass", 10.0, "info", 1.0, ev)


@check("TECH-021", scope="page_http")
def check_canonical_conflict(cp: Any) -> Verdict:
    """TECH-021 - a Link: rel=canonical header and an HTML canonical that
    disagree. Google's documented behaviour is to treat the conflict as a
    signal it may ignore entirely, so BOTH canonicals can be discarded."""
    if not _fetched(cp):
        return _na("page was not fetched")
    from audit_engine.analyzers.urls import same_page

    link_header = _h(cp, "link")
    header_canonical = None
    for part in link_header.split(","):
        if 'rel="canonical"' in part.lower() or "rel=canonical" in part.lower():
            m = re.search(r"<([^>]+)>", part)
            if m:
                header_canonical = m.group(1).strip()
                break
    parsed = getattr(cp, "parsed", None)
    html_canonical = getattr(parsed, "canonical", None) if parsed else None
    ev = {"header_canonical": header_canonical, "html_canonical": html_canonical}
    if not header_canonical and not html_canonical:
        return Verdict("warn", 5.0, "major", 1.0, ev,
                       "No canonical in either the HTML or the Link header. Duplicate "
                       "URLs of this page compete with each other.")
    if header_canonical and html_canonical and not same_page(header_canonical, html_canonical):
        return Verdict("fail", 1.0, "critical", 1.0, ev,
                       f"The Link header names {header_canonical} as canonical while the "
                       f"HTML names {html_canonical}. Google may discard both and pick its "
                       f"own, which is rarely the page you want ranking.")
    return Verdict("pass", 10.0, "info", 1.0, ev)
