"""Checks that open their own connection: TLS, DNS, hosting.

The plan gated this wave on a new dependency. It does not need one - Python's
``ssl`` and ``socket`` modules answer all three questions, and avoiding
``dnspython``/``cryptography`` keeps the deployment surface unchanged.

**Every probe goes through the SSRF guard.** These are the only checks that
open a socket to a host of their own accord rather than following the crawler,
so a redirect or a sitemap entry pointing at ``169.254.169.254`` would
otherwise become a way to reach cloud metadata from inside the audit.
"""

from __future__ import annotations

import socket
import ssl
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.context import CrawlContext
from audit_engine.analyzers.registry import check
from audit_engine.security import PrivateAddressError, validate_public_host

#: A handshake is a round trip. Keep it short: an unreachable host must not
#: stall an audit, and this is a diagnostic, not the crawl.
PROBE_TIMEOUT_S = 6.0

# CA/Browser Forum ballot SC-081 caps certificate lifetime, and every public CA
# now issues for 90 days or less, so a cert is routinely a third through its
# life. 14 days is the point at which an unattended renewal has already failed.
CERT_EXPIRY_CRITICAL_DAYS = 14
CERT_EXPIRY_WARN_DAYS = 30

#: Header fingerprints for the CDNs actually seen in the wild. Value is the
#: name to report; presence of the key is the signal.
CDN_HEADERS: dict[str, str] = {
    "cf-ray": "Cloudflare",
    "cf-cache-status": "Cloudflare",
    "x-amz-cf-id": "Amazon CloudFront",
    "x-amz-cf-pop": "Amazon CloudFront",
    "x-served-by": "Fastly",
    "x-fastly-request-id": "Fastly",
    "x-akamai-transformed": "Akamai",
    "x-akamai-request-id": "Akamai",
    "x-azure-ref": "Azure Front Door",
    "x-msedge-ref": "Azure CDN",
    "x-vercel-id": "Vercel",
    "x-nf-request-id": "Netlify",
    "x-sucuri-id": "Sucuri",
    "x-bunny-node": "BunnyCDN",
    "x-cdn": "generic (X-CDN header)",
}

#: Substrings in the Server header that name a CDN or edge proxy.
CDN_SERVER_TOKENS: dict[str, str] = {
    "cloudflare": "Cloudflare",
    "cloudfront": "Amazon CloudFront",
    "akamai": "Akamai",
    "fastly": "Fastly",
    "sucuri": "Sucuri",
    "bunnycdn": "BunnyCDN",
    "vercel": "Vercel",
    "netlify": "Netlify",
    "varnish": "Varnish (edge cache)",
}

#: Hostname fragments that identify a CDN in a DNS alias chain.
CDN_CNAME_TOKENS: dict[str, str] = {
    "cloudfront.net": "Amazon CloudFront",
    "akamaiedge.net": "Akamai",
    "akamai.net": "Akamai",
    "edgekey.net": "Akamai",
    "fastly.net": "Fastly",
    "cloudflare.net": "Cloudflare",
    "azureedge.net": "Azure CDN",
    "b-cdn.net": "BunnyCDN",
    "vercel-dns.com": "Vercel",
    "netlify.app": "Netlify",
}


def _host_of(ctx: CrawlContext) -> str | None:
    """The site host, or None if it fails the public-address guard."""
    host = urlsplit(ctx.site_url or "").hostname or ""
    if not host:
        return None
    try:
        return validate_public_host(host)
    except (PrivateAddressError, ValueError):
        return None


def _homepage_headers(ctx: CrawlContext) -> dict[str, str]:
    cp = ctx.by_url.get(ctx.home)
    return dict(getattr(cp, "headers", {}) or {}) if cp is not None else {}


def _refused(reason: str, **ev: Any) -> Verdict:
    return Verdict("n_a", 0.0, "info", 0.0, {"reason": reason, **ev})


# --------------------------------------------------------------------------

@check("TECH-056", scope="site_crawled")
def check_ssl_certificate(ctx: CrawlContext) -> Verdict:
    """TECH-056 - the certificate actually served, and when it expires.

    An expired certificate is the fastest way to lose every visitor at once:
    browsers show a full-page interstitial, not a warning, and Google drops
    HTTPS pages it cannot fetch.
    """
    host = _host_of(ctx)
    if not host:
        return _refused("site host is missing or not a public address")
    if not (ctx.site_url or "").lower().startswith("https://"):
        return _refused("site is not served over HTTPS, so there is no certificate "
                        "to inspect", site_url=ctx.site_url)
    context = ssl.create_default_context()
    try:
        with (
            socket.create_connection((host, 443), timeout=PROBE_TIMEOUT_S) as sock,
            context.wrap_socket(sock, server_hostname=host) as tls,
        ):
            cert = tls.getpeercert() or {}
            protocol = tls.version()
            cipher = tls.cipher()
    except ssl.SSLCertVerificationError as e:
        return Verdict("fail", 0.0, "critical", 1.0,
                       {"host": host, "verification_error": str(e)[:200]},
                       "The certificate does not validate. Every visitor sees a full-page "
                       "browser interstitial before reaching the site, and Google cannot "
                       "fetch the page at all.")
    except (OSError, ssl.SSLError) as e:
        return _refused(f"TLS probe failed: {type(e).__name__}: {str(e)[:120]}", host=host)

    not_after = cert.get("notAfter")
    days_left = None
    if not_after:
        try:
            expires = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(
                tzinfo=UTC)
            days_left = (expires - datetime.now(UTC)).days
        except ValueError:
            pass
    issuer = dict(x[0] for x in cert.get("issuer", ()) if x)
    sans = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
    ev = {"host": host, "issuer": issuer.get("organizationName") or issuer.get("commonName"),
          "not_after": not_after, "days_until_expiry": days_left,
          "tls_version": protocol, "cipher": cipher[0] if cipher else None,
          "san_count": len(sans), "covers_host": any(
              s == host or (s.startswith("*.") and host.endswith(s[1:])) for s in sans)}

    if days_left is not None and days_left < 0:
        return Verdict("fail", 0.0, "critical", 1.0, ev,
                       f"The certificate expired {abs(days_left)} days ago. Every visitor "
                       f"sees a browser interstitial.")
    if not ev["covers_host"] and sans:
        return Verdict("fail", 1.0, "critical", 1.0, ev,
                       f"The certificate does not cover {host}. Browsers reject it.")
    # TLS 1.0/1.1 were deprecated by RFC 8996 in 2021 and are refused by every
    # current browser.
    if protocol in ("TLSv1", "TLSv1.1"):
        return Verdict("fail", 2.0, "critical", 1.0, ev,
                       f"The server negotiated {protocol}, deprecated by RFC 8996 and "
                       f"refused by every current browser.")
    if days_left is not None and days_left <= CERT_EXPIRY_CRITICAL_DAYS:
        return Verdict("fail", 3.0, "critical", 1.0, ev,
                       f"The certificate expires in {days_left} days. If renewal is "
                       f"automated it has already failed; if it is manual, this is the "
                       f"last useful warning.")
    if days_left is not None and days_left <= CERT_EXPIRY_WARN_DAYS:
        return Verdict("warn", 7.0, "major", 1.0, ev,
                       f"The certificate expires in {days_left} days. Confirm automatic "
                       f"renewal is working.")
    return Verdict("pass", 10.0, "info", 1.0, ev)


@check("TECH-054", scope="site_crawled")
def check_cdn(ctx: CrawlContext) -> Verdict:
    """TECH-054 - is a CDN in front of the origin?

    Reported as informational. A CDN is not required, and a small local
    business served fast from one region does not need one - so this names what
    was found rather than failing a site for its absence.
    """
    headers = _homepage_headers(ctx)
    found: set[str] = set()
    signals: list[str] = []
    for key, name in CDN_HEADERS.items():
        if key in headers:
            found.add(name)
            signals.append(f"header {key}")
    server = (headers.get("server") or "").lower()
    for token, name in CDN_SERVER_TOKENS.items():
        if token in server:
            found.add(name)
            signals.append(f"Server: {server[:40]}")

    aliases: list[str] = []
    host = _host_of(ctx)
    if host:
        try:
            _name, alias_list, _ips = socket.gethostbyname_ex(host)
            aliases = list(alias_list)
        except (OSError, UnicodeError):
            aliases = []
    for alias in aliases:
        for token, name in CDN_CNAME_TOKENS.items():
            if token in alias.lower():
                found.add(name)
                signals.append(f"DNS alias {alias}")

    ev = {"cdn_detected": sorted(found), "signals": signals[:5],
          "dns_aliases": aliases[:5], "server": headers.get("server")}
    if found:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    if not headers:
        return _refused("the homepage response was not captured, so CDN headers "
                        "cannot be read")
    return Verdict("warn", 7.0, "minor", 0.8, ev,
                   "No CDN or edge cache detected. A CDN is not required - a site served "
                   "fast from one region is fine - but it is the usual fix when visitors "
                   "outside the origin's country see slow first bytes.")


@check("TECH-100", scope="site_crawled")
def check_hosting_performance(ctx: CrawlContext) -> Verdict:
    """TECH-100 - what the origin costs before any byte of content.

    Combines the measured response time with who is actually answering, so a
    slow response can be attributed to the host rather than guessed at.
    """
    from audit_engine.analyzers.headers import TTFB_GOOD_MS, TTFB_POOR_MS

    host = _host_of(ctx)
    if not host:
        # No DNS is attempted for a private host, so there is no SSRF here -
        # but reporting "hosting performance" for an address we will not
        # resolve would be a verdict about nothing.
        return _refused("site host is missing or not a public address")
    cp = ctx.by_url.get(ctx.home)
    if cp is None:
        return _refused("the homepage was not crawled")
    ms = int(getattr(cp, "response_ms", 0) or 0)
    headers = _homepage_headers(ctx)

    ips: list[str] = []
    reverse: str | None = None
    if host:
        try:
            _n, _a, ips = socket.gethostbyname_ex(host)
        except (OSError, UnicodeError):
            ips = []
        if ips:
            try:
                reverse = socket.gethostbyaddr(ips[0])[0]
            except (OSError, UnicodeError):
                reverse = None

    ev = {"host": host, "response_ms": ms, "resolved_ips": ips[:4],
          "reverse_dns": reverse, "server": headers.get("server"),
          "ip_count": len(ips),
          "good_threshold_ms": TTFB_GOOD_MS, "poor_threshold_ms": TTFB_POOR_MS}
    if ms <= 0:
        return _refused("no response timing was recorded for the homepage", **ev)
    if ms <= TTFB_GOOD_MS:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    where = f" Requests resolve to {reverse or (ips[0] if ips else 'an unidentified host')}."
    if ms <= TTFB_POOR_MS:
        return Verdict("warn", 6.0, "major", 0.85, ev,
                       f"The origin took {ms:,} ms to respond against a {TTFB_GOOD_MS} ms "
                       f"target.{where} Shared hosting and under-provisioned VPS instances "
                       f"are the usual cause.")
    return Verdict("fail", 2.0, "critical", 0.85, ev,
                   f"The origin took {ms:,} ms to respond, past the {TTFB_POOR_MS} ms "
                   f"'poor' threshold.{where} No amount of front-end optimisation can "
                   f"recover time lost before the first byte.")
