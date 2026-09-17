"""One URL normalisation, in one place.

Every site-wide analyzer used to derive the link graph with its own ad-hoc
normalisation, which is why their verdicts disagreed with each other: one
counted ``/about`` and ``/about/`` as two orphan pages, another as one.

**This module decides what "the same page" means to a client.** That is a
product decision as much as a technical one, so the policy is explicit,
configurable, and documented rather than buried in a regex.

Owner decision O-2 was resolved here as engineering, with the reasoning
recorded per rule. Flip any rule in ``NormalisationPolicy`` to change it; the
tier tests are unaffected but ``tests/test_urls.py`` pins current behaviour, so
a change breaks a test rather than silently redefining "duplicate".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Parameters that identify a traffic SOURCE, never page content. Stripping them
# is safe: the server returns byte-identical HTML with or without them, so two
# URLs differing only here are one page. Sourced from the union of Google
# Analytics / Google Ads / Meta / Microsoft / Mailchimp / TikTok documented
# click and campaign identifiers.
TRACKING_PARAMS = frozenset({
    # Google Analytics campaign parameters (utm_* is an open prefix, see below)
    "gclid", "gclsrc", "dclid", "gbraid", "wbraid", "gad_source", "gad_campaignid",
    # Meta
    "fbclid",
    # Microsoft / Bing
    "msclkid",
    # Mailchimp
    "mc_cid", "mc_eid",
    # Others in common use
    "igshid", "yclid", "ttclid", "twclid", "li_fat_id", "epik", "s_kwcid",
    "_ga", "_gl", "vero_id", "hsa_acc", "hsa_cam", "hsa_grp", "hsa_ad",
    "mkt_tok", "trk", "ref_src",
})

_TRACKING_PREFIXES = ("utm_", "pk_", "piwik_", "matomo_")

# Filenames a web server serves for the containing directory. ``/a/index.html``
# and ``/a/`` are then the same resource.
DIRECTORY_INDEX_FILES = frozenset({
    "index.html", "index.htm", "index.php", "index.asp", "index.aspx",
    "index.jsp", "index.shtml", "default.html", "default.htm", "default.asp",
    "default.aspx", "home.html",
})

_DEFAULT_PORTS = {"http": "80", "https": "443"}
_MULTI_SLASH = re.compile(r"/{2,}")


@dataclass(frozen=True)
class NormalisationPolicy:
    """What counts as the same page.

    Each default carries its reason. These are the answers to O-2.
    """

    # `/about` and `/about/` are ONE page. Servers almost universally serve
    # both, and every major CMS emits a canonical for one of them. Treating
    # them as two produces phantom duplicate-title and orphan findings, which
    # is the most common way a crawl-based audit embarrasses itself.
    unify_trailing_slash: bool = True

    # `/` and `/index.html` are ONE page, for the same reason.
    strip_directory_index: bool = True

    # `?utm_source=x` does NOT make a different page - the bytes are identical.
    # Any OTHER query parameter DOES: `?page=2` and `?id=7` are real, distinct
    # resources and collapsing them would hide genuine duplicate content.
    strip_tracking_params: bool = True

    # Remaining parameters are sorted so `?b=2&a=1` and `?a=1&b=2` match.
    sort_query: bool = True

    # Fragments are never sent to the server.
    strip_fragment: bool = True

    # Host is case-insensitive per RFC 3986; the PATH is not. Unix servers
    # serve /About and /about as different files, so path case is preserved.
    lowercase_host: bool = True

    # `https://x:443/` is `https://x/`.
    strip_default_port: bool = True

    # www and non-www are left alone: that is a redirect/canonical finding in
    # its own right (TECH-013), not a normalisation concern. Collapsing them
    # here would hide the very defect the audit exists to report.
    unify_www: bool = False


DEFAULT_POLICY = NormalisationPolicy()


def normalise(url: str, *, policy: NormalisationPolicy = DEFAULT_POLICY) -> str:
    """Return the canonical form of ``url`` under ``policy``.

    Total: never raises. A URL it cannot parse is returned stripped only.
    """
    if not url:
        return ""
    raw = url.strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw

    scheme = (parts.scheme or "").lower()
    host = parts.hostname or ""
    if policy.lowercase_host:
        host = host.lower()
    if policy.unify_www and host.startswith("www."):
        host = host[4:]

    netloc = host
    if parts.port is not None:
        port = str(parts.port)
        if not (policy.strip_default_port and _DEFAULT_PORTS.get(scheme) == port):
            netloc = f"{host}:{port}"
    # userinfo is dropped: it is a credential, and it must never reach an
    # evidence blob that ends up in a client PDF.

    path = _MULTI_SLASH.sub("/", parts.path or "/")
    if policy.strip_directory_index:
        head, _, last = path.rpartition("/")
        if last.lower() in DIRECTORY_INDEX_FILES:
            path = f"{head}/"
    if policy.unify_trailing_slash and len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    if not path:
        path = "/"

    query = parts.query
    if query:
        pairs = parse_qsl(query, keep_blank_values=True)
        if policy.strip_tracking_params:
            pairs = [
                (k, v) for k, v in pairs
                if k.lower() not in TRACKING_PARAMS
                and not k.lower().startswith(_TRACKING_PREFIXES)
            ]
        if policy.sort_query:
            pairs = sorted(pairs)
        query = urlencode(pairs, doseq=True)

    fragment = "" if policy.strip_fragment else parts.fragment
    return urlunsplit((scheme, netloc, path, query, fragment))


def same_page(a: str, b: str, *, policy: NormalisationPolicy = DEFAULT_POLICY) -> bool:
    """True when two URLs address the same page under ``policy``."""
    return normalise(a, policy=policy) == normalise(b, policy=policy)


def registrable_host(url: str) -> str:
    """Lowercased host with no port and no leading ``www.``.

    Used for internal-vs-external link classification, where www IS the same
    site even though `normalise` deliberately keeps them distinct as URLs.
    """
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def is_internal(url: str, site_url: str) -> bool:
    """True when ``url`` belongs to the same site as ``site_url``.

    A relative or scheme-relative URL with no host is internal by definition.
    """
    host = registrable_host(url)
    if not host:
        return bool(url) and not url.lower().startswith(
            ("mailto:", "tel:", "javascript:", "data:", "sms:", "callto:")
        )
    return host == registrable_host(site_url)
