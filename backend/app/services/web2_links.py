"""R2-15: a Web 2.0 property may never link to another Web 2.0 property.

WHY THIS IS THE STRICTEST RULE IN THE MODULE. Every other control here fights a
STATISTICAL tell - prose that reads alike, a burst that publishes too fast. Those need
judgement and thresholds. This one is different: a link from one of our properties to
another is a hard EDGE in a graph anyone can walk from the open web, with no inference
required. One crawl of our own published pages reconstructs the network, and it does so
whatever the prose looks like. R2 calls it "the single clearest network tell we can emit"
and bans it outright rather than rate-limiting it.

THE SECOND RULE IS THE MIRROR OF THE FIRST. Exactly one link to the client's money site
per article (WEB2-005). A property carrying three links to the same destination stops
reading as an article that happens to cite a source and starts reading as a link vehicle,
which is the thing the whole module is trying not to be.

DELIBERATELY BLUNT ON SHARED HOSTS. Matching is by normalised URL *and* by host, so a
draft on one Telegra.ph property linking to any Telegra.ph page is refused even when that
page is a stranger's. That over-blocks a genuine third-party reference on a path-based
host, and the trade is taken on purpose: the cost is one rejected reference an operator
can swap, and the alternative is emitting the one signal no amount of good prose hides.

Pure: takes a body and a set of known URLs, returns a verdict. No DB, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

#: Markdown links, autolinks and bare URLs. Deliberately greedy about what counts as a
#: link: a URL the writer left bare still resolves in the published HTML, so treating it
#: as "not really a link" would be a hole in the rule rather than a nicety.
_URL_RE = re.compile(r"https?://[^\s<>()\[\]\"'`]+", re.IGNORECASE)

#: Trailing characters that are punctuation in prose rather than part of the URL.
_TRAILING = ".,;:!?'\")]}" + "\u201d\u2019"  # incl. curly quotes, named to keep ruff happy


@dataclass(frozen=True)
class LinkVerdict:
    """What the link rule decided. ``code`` mirrors the similarity gate's shape so the
    approval endpoint and the UI read one machine-readable verdict for both."""

    verdict: str = "pass"  # pass | block
    code: str = ""
    detail: str = ""

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"


def extract_urls(body_md: str) -> list[str]:
    """Every outbound http(s) URL in the draft, in order, de-duplicated.

    Order is preserved so the first offender named in a refusal is the first one an
    operator will find when they scan the draft.
    """
    seen: set[str] = set()
    out: list[str] = []
    for match in _URL_RE.finditer(body_md or ""):
        url = match.group(0).rstrip(_TRAILING)
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def normalise(url: str) -> str:
    """A comparable form: scheme-insensitive, case-folded host, no port, no fragment.

    Two spellings of one page must not read as two different pages - otherwise the rule
    is defeated by a trailing slash, which is not a defence anyone should rely on.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    if "//" not in raw:
        raw = "//" + raw
    parts = urlsplit(raw if "://" in raw else "https:" + raw)
    host = (parts.hostname or "").lower()
    if not host:
        return ""
    path = (parts.path or "").rstrip("/")
    query = f"?{parts.query}" if parts.query else ""
    return f"{host}{path}{query}"


def host_of(url: str) -> str:
    """The bare lower-case host, or ``""`` when the input is not a URL."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    return (urlsplit(raw).hostname or "").lower()


def check_links(
    body_md: str,
    *,
    target_url: str = "",
    known_property_urls: set[str] | frozenset[str] = frozenset(),
) -> LinkVerdict:
    """Refuse a draft that links to one of our own properties, or over-links the client.

    ``known_property_urls`` is every published property URL plus every account's property
    URL, across ALL clients - the cross-client scope is the point, because the network a
    platform would walk does not stop at one client's boundary.
    """
    urls = extract_urls(body_md)
    if not urls:
        return LinkVerdict()

    known_norm = {normalise(u) for u in known_property_urls}
    known_norm.discard("")
    known_hosts = {host_of(u) for u in known_property_urls}
    known_hosts.discard("")

    target_host = host_of(target_url)
    # The money site is never a self-reference even if it also happens to be one of our
    # properties: blocking the article's own reason to exist would be the wrong refusal.
    known_norm.discard(normalise(target_url))
    known_hosts.discard(target_host)

    money_links = 0
    for url in urls:
        norm = normalise(url)
        host = host_of(url)
        if target_host and host == target_host:
            money_links += 1
            continue
        if norm in known_norm or host in known_hosts:
            return LinkVerdict(
                verdict="block",
                code=f"link_block:self_reference:{host}",
                detail=(
                    f"This draft links to another Web 2.0 property we built ({url}). "
                    "Inter-property linking is banned outright (R2-15): it is a hard edge "
                    "in a graph anyone can walk from the open web, and no amount of "
                    "distinct writing hides it. Link to a genuine third-party source "
                    "instead."
                ),
            )

    if money_links > 1:
        return LinkVerdict(
            verdict="block",
            code=f"link_block:money_site_repeat:{money_links}",
            detail=(
                f"This draft links to the client's site {money_links} times; exactly one "
                "is allowed (WEB2-005). More than one stops reading as an article that "
                "cites a source and starts reading as a link vehicle."
            ),
        )
    return LinkVerdict()
