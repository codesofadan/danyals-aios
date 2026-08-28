"""Did our link actually survive on the published page - and is it followed?

WHY THIS IS A SEPARATE MEASUREMENT. "Published" only means the platform's API accepted
the post. It does not mean our link is on the page. Platforms strip links, rewrite them
through redirectors, or add ``rel="nofollow"`` server-side, and none of that comes back
in the create response. Reporting a placement as delivered on the strength of a 201 is
how an agency invoices for a link that is not there.

So this fetches the page we were given and looks for the anchor ourselves. Three
outcomes, and they are deliberately three rather than two:

* ``found`` - the link is on the page; ``rel`` says whether it passes equity.
* ``missing`` - we fetched the page and our link was NOT on it. A real, actionable defect.
* ``unknown`` - we could not look (network, 403, timeout). NOT the same as missing, and
  never shown as a pass. A control that cannot distinguish "absent" from "unchecked"
  quietly converts every outage into a false accusation, or every failure into a tick.

PURE CORE, INJECTED FETCH. ``inspect_html`` is a pure function over an HTML string, so
the parsing is unit-tested with no network. The worker supplies the real fetcher.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

LinkState = Literal["found", "missing", "unknown"]

#: Anchor tags, non-greedy, case-insensitive. A full HTML parse is not worth a
#: dependency here: we need hrefs and their rel, and both live in the open tag.
_ANCHOR_RE = re.compile(r"<a\b([^>]*)>", re.IGNORECASE)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_REL_RE = re.compile(r"""rel\s*=\s*["']([^"']*)["']""", re.IGNORECASE)


@dataclass(frozen=True)
class LinkCheck:
    """What we measured about one placement's outbound link."""

    state: LinkState = "unknown"
    rel: str = ""
    detail: str = ""

    @property
    def found(self) -> bool | None:
        """Tri-state for the DB column: True / False / None (never looked)."""
        if self.state == "found":
            return True
        if self.state == "missing":
            return False
        return None

    @property
    def followed(self) -> bool:
        """A found link that passes equity. ``nofollow``, ``sponsored`` and ``ugc`` all
        stop it - they are different declarations but the same SEO outcome."""
        if self.state != "found":
            return False
        tokens = {t.strip().lower() for t in self.rel.replace(",", " ").split()}
        return not (tokens & {"nofollow", "sponsored", "ugc"})


class PageFetcher(Protocol):
    """Fetch a URL, returning HTML - or ``None`` when it could not be read.

    Must NEVER raise: an unreachable page is an ``unknown`` verdict, not a failed job.
    """

    def __call__(self, url: str) -> str | None: ...


#: Query parameters platforms bolt onto an outbound link for their own attribution.
#: MEASURED, not guessed: Ghost rewrote our href to `...?ref=purple-cormorant.pikapod.net`
#: on the first real publish, which a strict compare reported as a stripped link.
_TRACKING_PARAMS = frozenset({
    "ref", "source", "fbclid", "gclid", "mc_cid", "mc_eid",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
})


def _significant_query(query: str) -> str:
    """The query minus platform attribution noise.

    A query is NOT dropped wholesale: `?page=2` and `?id=7` select a different page, and
    ignoring them would match a link that points somewhere else entirely. Only the known
    attribution parameters are removed - the ones a platform adds to OUR url without
    changing which page it resolves to.
    """
    kept = [
        (k, v) for k, v in parse_qsl(query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    return urlencode(sorted(kept))


def normalize(url: str) -> str:
    """A comparable form of a URL: scheme+host lowercased, no fragment, no trailing
    slash, and no platform attribution parameters. Platforms routinely echo a link back
    with a different case, a stray slash, or their own `?ref=`, and a naive string
    compare would then report our own link as missing."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, host, path, _significant_query(parts.query), ""))


def inspect_html(html: str, target_url: str) -> LinkCheck:
    """Find our link in a fetched page and report its ``rel``. Pure.

    Matches on the NORMALIZED href so a scheme, case or trailing-slash difference does
    not read as a missing link. A platform that wraps the href in a redirector is
    reported as missing on purpose: a redirected link is not the link we placed, and
    calling it found would hide a real change in what the client received.
    """
    if not html or not target_url:
        return LinkCheck("unknown", detail="nothing to inspect")
    wanted = normalize(target_url)
    for tag in _ANCHOR_RE.finditer(html):
        attrs = tag.group(1)
        href_m = _HREF_RE.search(attrs)
        if href_m is None:
            continue
        if normalize(href_m.group(1)) != wanted:
            continue
        rel_m = _REL_RE.search(attrs)
        rel = (rel_m.group(1).strip() if rel_m else "")
        raw = href_m.group(1)
        detail = "link is on the page"
        if raw.strip() != target_url.strip():
            # Worth surfacing: the destination is ours, but the platform did not publish
            # the href we gave it. Silently normalising that away would hide a real
            # change to what the client received.
            detail = f"link is on the page (platform rewrote the href to {raw[:120]})"
        return LinkCheck("found", rel=rel, detail=detail)
    return LinkCheck("missing", detail="page fetched; our link was not on it")


def check_link(post_url: str, target_url: str, fetch: PageFetcher | None) -> LinkCheck:
    """Fetch the published page and measure our link. Never raises.

    A missing fetcher is ``unknown``, not a pass - "we could not check" must stay
    distinguishable from "we checked and it is fine", or the column silently becomes
    decoration.
    """
    if fetch is None:
        return LinkCheck("unknown", detail="no fetcher configured")
    if not post_url or not target_url:
        return LinkCheck("unknown", detail="no post URL or no target URL")
    try:
        html = fetch(post_url)
    except Exception as exc:  # a check must never fail the job it is checking
        return LinkCheck("unknown", detail=f"fetch failed: {exc!r}"[:180])
    if html is None:
        return LinkCheck("unknown", detail="page could not be fetched")
    return inspect_html(html, target_url)
